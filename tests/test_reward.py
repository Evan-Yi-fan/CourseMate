"""答题奖励计算测试（奖赏规则是服务端算的，必须锁死）。

游戏玩法本身改由 game/web 的 JS 实现并用 jsdom 测试，
这里只保留"灵玉怎么来"这一层的回归。
"""

from __future__ import annotations

import unittest

from game.systems.reward_system import AnswerRecord, RewardCalculator


class TestReward(unittest.TestCase):
    def setUp(self):
        self.calc = RewardCalculator()

    def _records(self, pattern: str) -> list[AnswerRecord]:
        return [AnswerRecord(i + 1, ch == "Y") for i, ch in enumerate(pattern)]

    def test_eight_correct_only_earns_eighty(self):
        """只按答对数发奖，不再叠加连对、完成或全对奖励。"""
        pattern = "YYYN" + "YYN" + "YYY"
        r = self.calc.calculate(self._records(pattern), 10)
        self.assertEqual(r["detail"]["correct"], 8)
        self.assertEqual(r["total"], 80)

    def test_perfect_score(self):
        r = self.calc.calculate(self._records("Y" * 10), 10)
        self.assertEqual(r["total"], 100)
        self.assertTrue(r["detail"]["perfect"])

    def test_wrong_does_not_subtract(self):
        r = self.calc.calculate(self._records("NNNNN"), 5)
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["detail"]["correct"], 0)

    def test_long_streak_has_no_extra_bonus(self):
        r = self.calc.calculate(self._records("YYYYY"), 5)
        self.assertFalse(any("连续答对" in i["name"] for i in r["items"]))
        self.assertEqual(r["total"], 50)

    def test_incomplete_quiz_has_no_complete_bonus(self):
        r = self.calc.calculate(self._records("YYY"), 10)
        self.assertFalse(any("完成全部" in i["name"] for i in r["items"]))
        self.assertEqual(r["detail"]["answered"], 3)

    def test_duplicate_question_settled_once(self):
        records = [AnswerRecord(1, True), AnswerRecord(1, True), AnswerRecord(2, True)]
        r = self.calc.calculate(records, 2)
        self.assertEqual(r["detail"]["answered"], 2)
        self.assertEqual(r["detail"]["duplicates_ignored"], 1)
        self.assertEqual(r["total"], 20)

    def test_total_questions_must_be_positive(self):
        with self.assertRaises(ValueError):
            self.calc.calculate([], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
