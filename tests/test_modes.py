"""答题模式层的测试：重点是"未作答必须计入总分"这个评分口径。"""

from __future__ import annotations

import unittest

from modes import all_modes, get_mode
from modes.base import complete_answers


QUESTIONS = [{"id": 1, "question": "a"}, {"id": 2, "question": "b"}, {"id": 3, "question": "c"}]


class TestCompleteAnswers(unittest.TestCase):
    def test_fills_missing_with_empty_string(self):
        out = complete_answers(QUESTIONS, {1: "A"})
        self.assertEqual(out, {1: "A", 2: "", 3: ""})

    def test_nothing_answered_still_returns_all(self):
        out = complete_answers(QUESTIONS, {})
        self.assertEqual(len(out), 3)
        self.assertTrue(all(v == "" for v in out.values()))

    def test_keeps_answers(self):
        out = complete_answers(QUESTIONS, {2: "B"})
        self.assertEqual(out[2], "B")
        self.assertEqual(out[1], "")

    def test_string_keys_are_normalized(self):
        out = complete_answers(QUESTIONS, {"1": "A"})
        self.assertEqual(out[1], "A")
        self.assertIsInstance(list(out)[0], int)

    def test_extra_keys_are_kept(self):
        """题库里没有的 id 不该被静默丢弃（判分时会因找不到题目而跳过）。"""
        out = complete_answers(QUESTIONS, {99: "C"})
        self.assertIn(99, out)


class TestModeRegistry(unittest.TestCase):
    def test_normal_mode_available(self):
        self.assertTrue(get_mode("normal").available)

    def test_registry_contains_normal_only(self):
        """游戏已独立成页，不再作为答题页里的模式。"""
        self.assertEqual({m.key for m in all_modes()}, {"normal"})

    def test_unknown_mode_raises(self):
        with self.assertRaises(KeyError):
            get_mode("game")

    def test_all_modes_declare_contract(self):
        for m in all_modes():
            self.assertIsInstance(m.key, str)
            self.assertIsInstance(m.label, str)
            self.assertIsInstance(m.description, str)
            self.assertIsInstance(m.available, bool)
            self.assertTrue(callable(m.render))


if __name__ == "__main__":
    unittest.main(verbosity=2)
