"""RAG 问答服务：检索 → 阈值判定 → 组装 Prompt → 调用模型 → 解析引用。

这里最容易被忽略、但决定体验的一步是**拒答**：
检索分数低于阈值时，宁可明确说"资料里没有"，也不让模型自由发挥。
否则用户会看到一段看起来很专业的编造内容，而项目"带来源"的卖点就废了。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Sequence

from agent.prompts import NO_EVIDENCE_ANSWER, build_qa_messages
from config.settings import Settings
from database import db
from knowledge.retriever import CourseIndex, Hit, RetrievalError
from services.llm_service import LLMError, LLMService

log = logging.getLogger(__name__)

_CITE_RE = re.compile(r"\[(\d{1,2})\]")

# 模型自己判定"资料不足"时会说这句话（Prompt 里明确要求它这么说）。
# 实测发现：相似度只能筛掉"完全不相关"（如食堂问题 0.27），
# 但"相关却不含答案"（如 JPEG 量化表，0.52）只能靠模型这句话识别。
NO_EVIDENCE_MARKER = "当前课程资料中没有找到足够依据"


@dataclass
class QAResult:
    answer: str
    sources: list[Hit]
    cited: list[int]                     # 实际被引用的片段编号（1-based）
    refused: bool
    reason: str = ""
    latency_ms: int = 0
    model: str = ""
    top_score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "sources": [h.as_dict() for h in self.sources],
            "cited": self.cited,
            "refused": self.refused,
            "reason": self.reason,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "top_score": self.top_score,
        }


def parse_citations(text: str, max_index: int) -> list[int]:
    """解析回答里的 [n]，丢掉越界的编号（防止模型编造不存在的引用）。"""
    found = {int(m) for m in _CITE_RE.findall(text or "")}
    return sorted(n for n in found if 1 <= n <= max_index)


class QAService:
    def __init__(self, settings: Settings, llm: LLMService | None = None):
        self.settings = settings
        self.llm = llm or LLMService(settings)

    # ------------------------------------------------------------------
    def ask(self, course_id: int, question: str, *, top_k: int | None = None,
            min_score: float | None = None, save_history: bool = True) -> QAResult:
        question = (question or "").strip()
        if not question:
            raise ValueError("问题不能为空")

        k = top_k or self.settings.qa_top_k
        threshold = self.settings.qa_min_score if min_score is None else min_score
        started = time.perf_counter()

        # 1) 检索
        try:
            hits = CourseIndex(self.settings, course_id).search(question, self._embedder(), k)
        except RetrievalError as exc:
            return QAResult(
                answer=f"检索资料时出错：{exc}", sources=[], cited=[], refused=True,
                reason="retrieval_error",
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        # 2) 阈值判定：低于阈值的一律不算依据
        usable = [h for h in hits if h.score >= threshold]
        top_score = hits[0].score if hits else 0.0

        if not usable:
            result = QAResult(
                answer=NO_EVIDENCE_ANSWER,
                sources=[],
                cited=[],
                refused=True,
                reason=(
                    f"检索到 {len(hits)} 条片段，但最高相似度 {top_score:.2f} "
                    f"低于阈值 {threshold:.2f}，判定为资料中没有依据。"
                ),
                latency_ms=int((time.perf_counter() - started) * 1000),
                top_score=top_score,
            )
            if save_history:
                self._save(course_id, question, result)
            return result

        # 3) 调模型
        messages = build_qa_messages(question, usable)
        try:
            chat = self.llm.chat(messages, temperature=0.1)
        except LLMError as exc:
            return QAResult(
                answer=f"回答失败：{exc}", sources=usable, cited=[], refused=True,
                reason="llm_error", top_score=top_score,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        cited = parse_citations(chat.text, len(usable))
        # 第二道判定：片段相关但不足以作答时，模型会说这句话，标记为"无依据"，
        # 否则界面会把它当成正常回答，用户也就注意不到答案其实没落到资料上。
        model_says_no_evidence = NO_EVIDENCE_MARKER in chat.text
        result = QAResult(
            answer=chat.text,
            sources=usable,
            cited=cited,
            refused=model_says_no_evidence,
            reason=(
                f"检索到的片段相关（最高 {top_score:.2f}），但模型判定其中没有答案"
                if model_says_no_evidence else ""
            ),
            latency_ms=int((time.perf_counter() - started) * 1000),
            model=chat.model,
            top_score=top_score,
        )
        if save_history:
            self._save(course_id, question, result)
        log.info(
            "问答完成 course=%s top=%.2f 片段=%d 引用=%s 耗时=%dms",
            course_id, top_score, len(usable), cited, result.latency_ms,
        )
        return result

    # ------------------------------------------------------------------
    def _embedder(self):
        # 延迟导入：只有真正检索时才加载（首次会加载本地模型，比较重）
        from knowledge.embeddings import get_embedder

        return get_embedder(self.settings)

    def _save(self, course_id: int, question: str, result: QAResult) -> None:
        """把问答写入 chat_messages（P1 的聊天历史，顺手落库不增加成本）。"""
        try:
            db.add_chat_message(self.settings.db_path, course_id, "user", question)
            db.add_chat_message(
                self.settings.db_path, course_id, "assistant", result.answer,
                sources=[h.as_dict() for h in result.sources],
            )
        except Exception as exc:  # 历史记录失败不该影响回答本身
            log.warning("问答历史保存失败: %s", exc)


def ask(settings: Settings, course_id: int, question: str, **kwargs) -> QAResult:
    return QAService(settings).ask(course_id, question, **kwargs)


def history(settings: Settings, course_id: int, limit: int = 50) -> Sequence[dict[str, Any]]:
    return db.list_chat_messages(settings.db_path, course_id, limit)
