"""学习分析：答题概览、错题明细、薄弱知识点、复习建议。

两条原则：
1. 所有数字都来自真实答题记录（任务书 §9 明确禁止虚构统计）；
2. 没有数据时不编造——直接告诉用户"还没答题"。
"""

from __future__ import annotations

import logging
from typing import Any

from config.settings import Settings
from database import db
from services.llm_service import LLMError, LLMService

log = logging.getLogger(__name__)

ADVICE_SYSTEM = """你是一名耐心的课程助教。根据学生的答题记录给出复习建议。

要求：
1. 只依据给出的错题和知识点，不要虚构学生没有做过的题；
2. 给 3 条建议，每条 1-2 句话，必须具体到"看哪一页/复习哪个概念/做什么练习"；
3. 不要写"继续努力""保持良好心态"这类空话；
4. 用中文，直接输出建议正文，不要标题，不要 Markdown 代码块。"""


def overview(settings: Settings, course_id: int) -> dict[str, Any]:
    """一次取齐分析页要用的全部数据。"""
    stats = db.attempt_stats(settings.db_path, course_id)
    wrong = db.list_attempts(settings.db_path, course_id, only_wrong=True, limit=50)
    recent = db.list_attempts(settings.db_path, course_id, only_wrong=False, limit=10)

    return {
        **stats,
        "wrong_questions": wrong,
        "recent": recent,
        "has_data": stats["total"] > 0,
        "weak_points": [k for k in stats["by_knowledge"] if k["wrong"] > 0],
    }


def _build_prompt(course_name: str, overview_data: dict[str, Any]) -> str:
    lines = [
        f"课程：{course_name}",
        f"共作答 {overview_data['total']} 题，答对 {overview_data['correct']} 题，"
        f"正确率 {overview_data['accuracy']:.0%}。",
        "",
        "各知识点情况：",
    ]
    for kp in overview_data["by_knowledge"]:
        lines.append(f"- {kp['knowledge_point']}：共 {kp['total']} 题，错 {kp['wrong']} 题")

    wrong = overview_data["wrong_questions"][:6]
    if wrong:
        lines.append("")
        lines.append("做错的题目：")
        for w in wrong:
            lines.append(f"- {w['question']}（正确答案 {w['answer']}，学生选 {w['user_answer'] or '未作答'}，"
                         f"知识点：{w['knowledge_point']}）")
    return "\n".join(lines)


def advice(settings: Settings, course_id: int, course_name: str = "",
           llm: LLMService | None = None) -> dict[str, Any]:
    """基于真实错题生成 3 条复习建议。没有数据或模型不可用时返回可读原因。"""
    data = overview(settings, course_id)
    if not data["has_data"]:
        return {"ok": False, "reason": "还没有答题记录，先去做几道题再来。", "text": ""}

    try:
        service = llm or LLMService(settings)
        chat = service.chat(
            [{"role": "system", "content": ADVICE_SYSTEM},
             {"role": "user", "content": _build_prompt(course_name, data)}],
            temperature=0.4,
        )
    except LLMError as exc:
        return {"ok": False, "reason": f"生成建议失败：{exc}", "text": ""}

    return {"ok": True, "reason": "", "text": chat.text, "model": chat.model,
            "latency_ms": chat.latency_ms}
