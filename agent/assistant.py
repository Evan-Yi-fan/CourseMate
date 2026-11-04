"""单 Agent：理解意图 → 选工具 → 执行 → 组织回复。

路由策略（任务书允许"规则或一次轻量 LLM 分类"）：
- 先用**规则**命中高置信关键词（"出 3 道题""看看我的错题"），省一次模型调用；
- 规则拿不准时，再调一次轻量 LLM 做分类；
- 模型分类失败就退回知识问答——这是最常用、也最不会出错的兜底。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from agent.tools import TOOL_SPECS, ToolError, run_tool
from config.settings import Settings
from services.llm_service import LLMError, LLMService

log = logging.getLogger(__name__)

INTENTS = {"knowledge_qa": "knowledge_search",
           "generate_quiz": "generate_quiz",
           "analyze_mistakes": "analyze_mistakes"}

_ROUTE_SYSTEM = """你是意图分类器。根据用户这句话，判断它属于哪一类任务，只输出 JSON。

可选任务：
- knowledge_qa：询问课程知识（默认）
- generate_quiz：要求出题/练习题
- analyze_mistakes：查看答题统计/错题/正确率

输出格式：{"intent": "knowledge_qa", "args": {}}
出题时在 args 里给 {"count": 3, "question_type": "single", "topic": "可选"}
不要输出任何解释。"""

# 高置信规则：命中就直接路由，不花一次模型调用
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("analyze_mistakes", re.compile(r"(错题|正确率|答题记录|学习报告|我考得|薄弱点|分析一下我的)")),
    ("generate_quiz", re.compile(r"(出.{0,8}题|出题|来.{0,6}道|练习题|做题|考考我|生成.{0,6}题)")),
]

_NUM_CN = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


@dataclass
class AgentReply:
    intent: str
    tool: str | None
    ok: bool
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    routed_by: str = "rule"        # rule | llm | fallback

    def as_dict(self) -> dict[str, Any]:
        return {"intent": self.intent, "tool": self.tool, "ok": self.ok,
                "message": self.message, "routed_by": self.routed_by, "payload": self.payload}


def parse_count(text: str, default: int = 3) -> int:
    """从"出 5 道题""来两道题"里抠数量。"""
    m = re.search(r"(\d+)\s*道", text)
    if m:
        return max(1, min(int(m.group(1)), 10))
    for cn, val in _NUM_CN.items():
        if f"{cn}道" in text:
            return val
    return default


def parse_question_type(text: str) -> str:
    return "judge" if ("判断" in text) else "single"


def route_by_rule(text: str) -> tuple[str, dict[str, Any]] | None:
    for intent, pattern in _RULES:
        if pattern.search(text):
            if intent == "generate_quiz":
                return intent, {"count": parse_count(text),
                                "question_type": parse_question_type(text)}
            return intent, {}
    return None


class Assistant:
    def __init__(self, settings: Settings, llm: LLMService | None = None):
        self.settings = settings
        self.llm = llm or LLMService(settings)

    # ------------------------------------------------------------------
    def route(self, text: str) -> tuple[str, dict[str, Any], str]:
        """返回 (intent, args, routed_by)。"""
        rule = route_by_rule(text)
        if rule:
            return rule[0], rule[1], "rule"

        try:
            chat = self.llm.chat(
                [{"role": "system", "content": _ROUTE_SYSTEM},
                 {"role": "user", "content": text}],
                temperature=0.0, max_tokens=120, json_mode=True,
            )
            raw = chat.text.strip()
            start, end = raw.find("{"), raw.rfind("}")
            obj = json.loads(raw[start:end + 1]) if start != -1 else {}
            intent = str(obj.get("intent", "")).strip()
            args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
            if intent in INTENTS:
                return intent, args, "llm"
        except (LLMError, json.JSONDecodeError, ValueError) as exc:
            log.warning("意图分类失败，退回知识问答: %s", exc)

        return "knowledge_qa", {"query": text}, "fallback"

    # ------------------------------------------------------------------
    def handle(self, course_id: int, text: str) -> AgentReply:
        text = (text or "").strip()
        if not text:
            raise ValueError("输入不能为空")

        intent, args, routed_by = self.route(text)
        tool = INTENTS[intent]
        if tool == "knowledge_search":
            args = {"query": args.get("query") or text}
        elif tool == "generate_quiz":
            args = {
                "count": int(args.get("count", parse_count(text)) or 3),
                "question_type": args.get("question_type") or parse_question_type(text),
                "topic": args.get("topic"),
            }

        try:
            payload = run_tool(tool, self.settings, course_id, args)
        except ToolError as exc:
            return AgentReply(intent=intent, tool=tool, ok=False, message=str(exc),
                              routed_by=routed_by)
        except Exception as exc:  # noqa: BLE001
            log.exception("工具执行异常 %s", tool)
            return AgentReply(intent=intent, tool=tool, ok=False,
                              message=f"{type(exc).__name__}: {exc}", routed_by=routed_by)

        return AgentReply(intent=intent, tool=tool, ok=True,
                          message=self._compose(intent, payload),
                          payload=payload, routed_by=routed_by)

    # ------------------------------------------------------------------
    @staticmethod
    def _compose(intent: str, payload: dict[str, Any]) -> str:
        if intent == "knowledge_qa":
            return payload.get("answer", "")
        if intent == "generate_quiz":
            n = len(payload.get("questions") or [])
            return f"已经根据课程资料生成 {n} 道题，去「智能试题」作答即可。"
        if intent == "analyze_mistakes":
            return payload.get("summary", "已统计答题情况。")
        return "已执行。"
