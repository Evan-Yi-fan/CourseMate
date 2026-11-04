"""Agent 可调用的工具。

约定（任务书 §4.3）：
- 工具函数只做**确定性业务逻辑**，不直接让模型碰数据库/文件；
- 参数一律在 Python 侧校验，模型传错就返回结构化错误，而不是抛异常把页面打崩；
- 返回值统一是 dict，便于既被 Agent 使用，也被界面直接渲染。
"""

from __future__ import annotations

import logging
from typing import Any

from config.settings import Settings
from database import db
from knowledge.retriever import CourseIndex
from services.quiz_service import QuizError, QuizService
from services.qa_service import QAService

log = logging.getLogger(__name__)

# 给模型看的工具说明（也用于生成路由 Prompt）
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "knowledge_search",
        "description": "在当前课程资料中检索并回答知识问题，返回答案与来源引用。",
        "params": {"query": "string，用户的问题"},
    },
    {
        "name": "generate_quiz",
        "description": "根据课程资料生成练习题。",
        "params": {
            "count": "int，1-10",
            "question_type": "single 或 judge",
            "topic": "string，可选的知识点",
        },
    },
    {
        "name": "analyze_mistakes",
        "description": "统计当前课程的答题正确率与薄弱知识点。",
        "params": {},
    },
]

VALID_QTYPES = {"single", "judge"}


class ToolError(RuntimeError):
    """工具参数或执行出错，消息可直接展示。"""


def _require_course(settings: Settings, course_id: int) -> None:
    if not db.get_course(settings.db_path, int(course_id)):
        raise ToolError(f"课程 {course_id} 不存在")


def knowledge_search(settings: Settings, course_id: int, query: str,
                     top_k: int | None = None) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        raise ToolError("query 不能为空")
    if top_k is not None:
        top_k = int(top_k)
        if not 1 <= top_k <= 10:
            raise ToolError("top_k 必须在 1~10 之间")
    _require_course(settings, course_id)
    r = QAService(settings).ask(course_id, query, top_k=top_k, save_history=False)
    return {"tool": "knowledge_search", **r.as_dict()}


def generate_quiz(settings: Settings, course_id: int, count: int = 3,
                  question_type: str = "single", topic: str | None = None) -> dict[str, Any]:
    try:
        count = int(count)
    except (TypeError, ValueError) as exc:
        raise ToolError("count 必须是整数") from exc
    if not 1 <= count <= 10:
        raise ToolError("count 必须在 1~10 之间")
    if question_type not in VALID_QTYPES:
        raise ToolError(f"question_type 只能是 single / judge，收到 {question_type!r}")

    _require_course(settings, course_id)
    try:
        questions = QuizService(settings).generate(
            course_id, count=count, question_type=question_type,
            topic=(topic or "").strip() or None,
        )
    except QuizError as exc:
        raise ToolError(str(exc)) from exc
    return {"tool": "generate_quiz", "questions": [q.as_dict() for q in questions]}


def analyze_mistakes(settings: Settings, course_id: int) -> dict[str, Any]:
    _require_course(settings, course_id)
    stats = db.attempt_stats(settings.db_path, course_id)
    if stats["total"] == 0:
        return {"tool": "analyze_mistakes", **stats,
                "summary": "还没有答题记录，先去「智能试题」做几道题吧。"}

    weak = [k for k in stats["by_knowledge"] if k["wrong"] > 0][:3]
    if weak:
        tips = "；".join(f"{k['knowledge_point']}（错 {k['wrong']}/{k['total']} 题）" for k in weak)
        summary = f"共作答 {stats['total']} 题，正确率 {stats['accuracy']:.0%}。薄弱知识点：{tips}。"
    else:
        summary = f"共作答 {stats['total']} 题，正确率 {stats['accuracy']:.0%}，暂无明显薄弱点。"
    return {"tool": "analyze_mistakes", **stats, "summary": summary}


_HANDLERS = {
    "knowledge_search": knowledge_search,
    "generate_quiz": generate_quiz,
    "analyze_mistakes": analyze_mistakes,
}


def run_tool(name: str, settings: Settings, course_id: int, args: dict[str, Any]) -> dict[str, Any]:
    """统一入口：校验工具名与参数，异常转成结构化错误。"""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ToolError(f"未知工具：{name}")
    try:
        return handler(settings, course_id, **(args or {}))
    except TypeError as exc:
        # 模型多传/少传参数时，给出可读信息而不是堆栈
        raise ToolError(f"工具 {name} 的参数不匹配：{exc}") from exc
