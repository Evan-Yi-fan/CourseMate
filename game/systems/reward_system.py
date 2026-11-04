"""答题奖励计算。

关键约束（任务书 §3「防刷要求」）：
- 奖励由**后端**根据已保存的作答记录计算，不接受前端传来的金额或"答对"标记；
- 同一道题在一局内只能结算一次，重复练习不重复发奖。

所以 `calculate()` 的第一件事就是按 question_id 去重，
并把"这一局应该有多少题"作为参数传进来，用来判断"是否完成全部题目"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from game.config import economy_config as cfg


@dataclass
class AnswerRecord:
    """一条作答记录。is_correct 必须来自后端判分结果。"""
    question_id: int
    is_correct: bool

    @classmethod
    def from_grade(cls, item: dict[str, Any]) -> "AnswerRecord":
        qid = item.get("question_id")
        if qid is None:
            raise ValueError("作答记录缺少 question_id")
        return cls(question_id=int(qid), is_correct=bool(item.get("is_correct")))


class RewardCalculator:
    """按配置计算灵玉奖励，返回明细，便于界面展示。"""

    def calculate(self, records: Iterable[AnswerRecord], total_questions: int) -> dict[str, Any]:
        if total_questions <= 0:
            raise ValueError("total_questions 必须为正整数")

        seen: dict[int, bool] = {}
        duplicates = 0
        for r in records:
            if r.question_id in seen:
                duplicates += 1
                continue          # 同一题只结算一次
            seen[r.question_id] = bool(r.is_correct)

        # 只统计属于本局题库的记录，防止旧局记录混进来刷分
        valid = {k: v for k, v in seen.items()}
        correct = sum(1 for v in valid.values() if v)
        wrong = len(valid) - correct
        answered = len(valid)

        items: list[dict[str, Any]] = []
        total = 0

        base = correct * cfg.REWARD_PER_CORRECT
        if base:
            items.append({"name": f"答对 {correct} 题", "amount": base})
            total += base

        streak = self._longest_streak(valid)
        complete = answered >= total_questions
        perfect = complete and correct == total_questions and wrong == 0

        return {
            "total": total,
            "items": items,
            "detail": {
                "answered": answered,
                "correct": correct,
                "wrong": wrong,
                "total_questions": total_questions,
                "longest_streak": streak,
                "duplicates_ignored": duplicates,
                "completed": complete,
                "perfect": perfect,
            },
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _longest_streak(ordered: dict[int, bool]) -> int:
        """最长连对。

        字典按插入顺序迭代，也就是按题目提交顺序；
        这里不要求"当前还在连"，只取历史最长，V1 够用。
        """
        best = cur = 0
        for _, ok in ordered.items():
            cur = cur + 1 if ok else 0
            best = max(best, cur)
        return best
