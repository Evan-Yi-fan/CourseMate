"""试题服务：生成 → 严格校验 → 落库；作答 → 程序判分 → 落库。

两个刻意的设计：
1. **校验比生成更重要**。模型输出 JSON 不可全信，所以对结构、数量、
   选项 key、答案归属逐项检查，不合格就重试一次，再不合格就明确报错，
   绝不把半成品塞进数据库。
2. **判分绝不交给模型**。客观题的正确答案是结构化字段，
   比对由 Python 完成，模型只负责"出题+解析"。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from agent.prompts import QUIZ_SYSTEM
from config.settings import Settings
from database import db
from knowledge.retriever import CourseIndex, Hit, RetrievalError
from services.llm_service import LLMError, LLMService

log = logging.getLogger(__name__)

MAX_COUNT = 10
VALID_TYPES = {"single", "judge"}
_CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.M)


class QuizError(RuntimeError):
    """出题失败，消息面向用户。"""


class QuizValidationError(QuizError):
    """模型返回的结构不合法。"""


@dataclass
class Question:
    id: int
    question: str
    question_type: str
    options: list[dict[str, str]]
    answer: str
    explanation: str
    knowledge_point: str

    def public(self) -> dict[str, Any]:
        """给界面用：**不含答案**，防止在渲染层泄露。"""
        return {
            "id": self.id, "question": self.question, "question_type": self.question_type,
            "options": self.options, "knowledge_point": self.knowledge_point,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "question": self.question, "question_type": self.question_type,
            "options": self.options, "answer": self.answer,
            "explanation": self.explanation, "knowledge_point": self.knowledge_point,
        }


# ----------------------------------------------------------------------
# JSON 抽取与校验
# ----------------------------------------------------------------------

def extract_json(text: str) -> dict[str, Any]:
    """从模型输出里抠出 JSON 对象，容忍 ```json 围栏和前后废话。"""
    raw = _CODE_FENCE.sub("", (text or "").strip())
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise QuizValidationError("模型没有返回 JSON 对象。")
    try:
        obj = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        raise QuizValidationError(f"模型返回的 JSON 解析失败：{exc.msg}") from exc
    if not isinstance(obj, dict):
        raise QuizValidationError("模型返回的不是 JSON 对象。")
    return obj


def _clean_options(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        raise QuizValidationError("options 必须是数组。")
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            key = str(item.get("key", "")).strip().upper()
            text = str(item.get("text", "")).strip()
        elif isinstance(item, str):
            key, text = "", item.strip()
        else:
            raise QuizValidationError("option 必须是对象或字符串。")
        if not text:
            raise QuizValidationError("存在内容为空的选项。")
        out.append({"key": key, "text": text})
    # 没给 key 的自动补 A/B/C/D
    for i, opt in enumerate(out):
        if not opt["key"]:
            opt["key"] = "ABCDEFGH"[i]
    return out


def validate_questions(obj: dict[str, Any], expected_count: int,
                       expected_type: str) -> list[dict[str, Any]]:
    """逐项校验，任何一项不合格就整体拒绝（不静默丢弃坏题，否则数量对不上）。"""
    items = obj.get("questions")
    if not isinstance(items, list) or not items:
        raise QuizValidationError("返回结果里没有 questions 数组。")
    if len(items) != expected_count:
        raise QuizValidationError(f"要求 {expected_count} 道题，实际返回 {len(items)} 道。")

    cleaned: list[dict[str, Any]] = []
    for idx, q in enumerate(items, start=1):
        if not isinstance(q, dict):
            raise QuizValidationError(f"第 {idx} 题不是对象。")
        text = str(q.get("question", "")).strip()
        if len(text) < 5:
            raise QuizValidationError(f"第 {idx} 题题干过短或为空。")

        qtype = str(q.get("type", expected_type)).strip().lower()
        if qtype not in VALID_TYPES:
            raise QuizValidationError(f"第 {idx} 题类型非法：{qtype}")
        if qtype != expected_type:
            raise QuizValidationError(
                f"第 {idx} 题类型为 {qtype}，与要求的 {expected_type} 不一致。"
            )

        options = _clean_options(q.get("options"))
        if qtype == "single":
            if len(options) != 4:
                raise QuizValidationError(f"第 {idx} 题应为 4 个选项，实际 {len(options)} 个。")
        else:  # judge
            if len(options) != 2:
                raise QuizValidationError(f"第 {idx} 判断题应为 2 个选项，实际 {len(options)} 个。")

        keys = [o["key"] for o in options]
        if len(set(keys)) != len(keys):
            raise QuizValidationError(f"第 {idx} 题选项 key 有重复。")

        answer = str(q.get("answer", "")).strip().upper()
        if answer not in keys:
            raise QuizValidationError(f"第 {idx} 题答案 {answer!r} 不在选项 {keys} 中。")

        cleaned.append({
            "question": text,
            "question_type": qtype,
            "options": options,
            "answer": answer,
            "explanation": str(q.get("explanation", "")).strip(),
            "knowledge_point": str(q.get("knowledge_point", "")).strip() or "未标注",
        })
    return cleaned


# ----------------------------------------------------------------------
# 生成
# ----------------------------------------------------------------------

def _build_context(hits: Iterable[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        loc = h.filename + (f" 第 {h.page} 页" if h.page else "")
        blocks.append(f"[{i}] {loc}\n{h.text.strip()}")
    return "\n\n".join(blocks)


class QuizService:
    def __init__(self, settings: Settings, llm: LLMService | None = None):
        self.settings = settings
        self.llm = llm or LLMService(settings)

    def generate(self, course_id: int, *, count: int = 5, question_type: str = "single",
                 topic: str | None = None, save: bool = True,
                 retries: int = 1, document_ids: list[int] | None = None) -> list[Question]:
        if question_type not in VALID_TYPES:
            raise QuizError(f"不支持的题型：{question_type}")
        count = max(1, min(int(count), MAX_COUNT))

        if document_ids is not None:
            document_ids = list(dict.fromkeys(int(did) for did in document_ids))
            if not document_ids:
                raise QuizError("请至少选择一份课程资料。")
            available = {d["id"] for d in db.list_documents(self.settings.db_path, course_id)
                         if d["status"] == "ready"}
            if not set(document_ids) <= available:
                raise QuizError("所选资料不属于当前课程或尚未入库，请重新选择。")

        # 1) 找上下文：指定了知识点就语义检索，否则全课程取样
        try:
            index = CourseIndex(self.settings, course_id)
            from knowledge.embeddings import get_embedder

            if document_ids is not None:
                hits = index.sample_documents(document_ids)
            else:
                hits = (index.search(topic, get_embedder(self.settings), 6) if topic
                        else index.sample(6))
        except RetrievalError as exc:
            raise QuizError(f"读取课程资料失败：{exc}") from exc

        if not hits:
            raise QuizError("这门课程还没有可用的资料片段，请先上传资料。")

        type_label = "单选题（每题 4 个选项，只有 1 个正确答案）" if question_type == "single" \
            else "判断题（每题 2 个选项：正确 / 错误）"
        user_prompt = (
            f"请根据下面的课程资料出 {count} 道{type_label}。\n"
            + (f"尽量围绕这个知识点：{topic}\n" if topic else "")
            + f"\n【资料片段】\n{_build_context(hits)}\n\n"
            f"只输出 JSON，questions 数组长度必须等于 {count}。"
        )

        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                chat = self.llm.chat(
                    [{"role": "system", "content": QUIZ_SYSTEM},
                     {"role": "user", "content": user_prompt}],
                    temperature=0.4, json_mode=True,
                )
                obj = extract_json(chat.text)
                cleaned = validate_questions(obj, count, question_type)
            except (QuizValidationError, LLMError) as exc:
                last_err = exc
                log.warning("出题第 %d/%d 次失败：%s", attempt + 1, retries + 1, exc)
                continue

            questions = []
            for item in cleaned:
                qid = 0
                if save:
                    qid = db.add_question(
                        self.settings.db_path, course_id,
                        question=item["question"], question_type=item["question_type"],
                        options=item["options"], answer=item["answer"],
                        explanation=item["explanation"],
                        knowledge_point=item["knowledge_point"],
                    )
                questions.append(Question(id=qid, **item))
            log.info("出题成功：%d 道（%s，课程 %d）", len(questions), question_type, course_id)
            return questions

        raise QuizError(
            f"出题失败（已重试 {retries} 次）：{last_err}。"
            "可以少要几道题，或换一个更具体的知识点再试。"
        )


# ----------------------------------------------------------------------
# 判分
# ----------------------------------------------------------------------

@dataclass
class GradeResult:
    question_id: int
    is_correct: bool
    correct_answer: str
    user_answer: str
    explanation: str
    knowledge_point: str
    question: str = ""


def grade_answer(settings: Settings, question_id: int, user_answer: str,
                 *, save: bool = True) -> GradeResult:
    """判分：纯字符串比对，不看模型脸色。"""
    q = db.get_question(settings.db_path, question_id)
    if not q:
        raise QuizError(f"题目 {question_id} 不存在")

    user_answer = (user_answer or "").strip().upper()
    correct = str(q["answer"]).strip().upper()
    is_correct = bool(user_answer) and user_answer == correct

    if save:
        db.add_attempt(settings.db_path, question_id, user_answer, is_correct)

    return GradeResult(
        question_id=question_id,
        is_correct=is_correct,
        correct_answer=correct,
        user_answer=user_answer,
        explanation=q.get("explanation", ""),
        knowledge_point=q.get("knowledge_point", ""),
        question=q.get("question", ""),
    )


def grade_batch(settings: Settings, answers: dict[int, str]) -> dict[str, Any]:
    """一次提交多题，返回总分与逐题结果。"""
    results: list[GradeResult] = []
    for qid, ans in answers.items():
        try:
            results.append(grade_answer(settings, int(qid), ans))
        except QuizError:
            continue
    total = len(results)
    correct = sum(1 for r in results if r.is_correct)
    return {
        "total": total,
        "correct": correct,
        "score": round(correct / total * 100, 1) if total else 0.0,
        "results": [
            {
                "question_id": r.question_id, "question": r.question,
                "is_correct": r.is_correct, "correct_answer": r.correct_answer,
                "user_answer": r.user_answer, "explanation": r.explanation,
                "knowledge_point": r.knowledge_point,
            }
            for r in results
        ],
    }
