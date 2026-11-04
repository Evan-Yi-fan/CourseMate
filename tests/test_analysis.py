"""阶段 E 的测试：学习分析的数据口径与建议生成。

关键是"不许编数据"：
没有答题记录时，overview 必须是 total=0、advice 必须明确拒绝而不是给一段泛泛而谈。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from config.settings import Settings
from database import db
from knowledge import retriever as retriever_mod
from services import analysis_service, document_service as docsvc
from services.llm_service import ChatResult
from services.quiz_service import QuizService

DOC = (
    "直方图均衡化通过累积分布函数把原始灰度映射到均匀分布，从而增强对比度。\n"
    "Canny 边缘检测包含高斯平滑、计算梯度、非极大值抑制、双阈值滞后连接四步。"
)


def payload() -> dict:
    return {"questions": [
        {
            "question": "直方图均衡化的作用是什么？",
            "type": "single",
            "options": [{"key": "A", "text": "增强对比度"}, {"key": "B", "text": "压缩体积"},
                        {"key": "C", "text": "去噪声"}, {"key": "D", "text": "边缘检测"}],
            "answer": "A", "explanation": "均衡化增强对比度。", "knowledge_point": "直方图",
        },
        {
            "question": "Canny 的第三步是什么？",
            "type": "single",
            "options": [{"key": "A", "text": "高斯平滑"}, {"key": "B", "text": "非极大值抑制"},
                        {"key": "C", "text": "双阈值"}, {"key": "D", "text": "求梯度"}],
            "answer": "B", "explanation": "第三步是非极大值抑制。", "knowledge_point": "边缘检测",
        },
    ]}


class FakeLLM:
    def __init__(self, text: str = "1. 回看第 2 页的累积分布函数。\n2. 复习 Canny 四步。\n3. 做 3 道滤波题。"):
        self.text = text
        self.calls: list[list[dict]] = []

    def chat(self, messages, **kwargs) -> ChatResult:
        self.calls.append(messages)
        return ChatResult(text=self.text, model="fake", latency_ms=1)


class AnalystTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.settings = Settings(
            db_path=root / "t.db", chroma_path=root / "chroma", upload_dir=root / "up",
            embedding_provider="hash", embedding_model="hash-test", embedding_dim=256,
        )
        self.settings.ensure_dirs()
        db.init_db(self.settings.db_path)
        self.course_id = db.create_course(self.settings.db_path, "数字图像处理")
        docsvc.handle_upload(self.settings, self.course_id, "note.txt", DOC.encode("utf-8"))

    def tearDown(self):
        retriever_mod.reset_clients()
        self.tmp.cleanup()

    def make_questions(self):
        llm = FakeLLM(json.dumps(payload(), ensure_ascii=False))
        return QuizService(self.settings, llm=llm).generate(
            self.course_id, count=2, question_type="single")


class TestOverview(AnalystTestBase):
    def test_empty_state_is_honest(self):
        data = analysis_service.overview(self.settings, self.course_id)
        self.assertEqual(data["total"], 0)
        self.assertFalse(data["has_data"])
        self.assertEqual(data["wrong_questions"], [])
        self.assertEqual(data["weak_points"], [])

    def test_counts_after_answering(self):
        qs = self.make_questions()
        db.add_attempt(self.settings.db_path, qs[0].id, "A", True)
        db.add_attempt(self.settings.db_path, qs[1].id, "A", False)

        data = analysis_service.overview(self.settings, self.course_id)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["correct"], 1)
        self.assertEqual(data["accuracy"], 0.5)
        self.assertTrue(data["has_data"])
        self.assertEqual(len(data["wrong_questions"]), 1)
        self.assertEqual(data["wrong_questions"][0]["knowledge_point"], "边缘检测")
        self.assertEqual(data["weak_points"][0]["knowledge_point"], "边缘检测")


class TestAdvice(AnalystTestBase):
    def test_refuses_without_data(self):
        out = analysis_service.advice(self.settings, self.course_id, "数字图像处理",
                                      llm=FakeLLM())
        self.assertFalse(out["ok"])
        self.assertIn("还没有答题记录", out["reason"])
        self.assertEqual(out["text"], "")

    def test_prompt_contains_real_mistakes(self):
        qs = self.make_questions()
        db.add_attempt(self.settings.db_path, qs[1].id, "A", False)

        llm = FakeLLM()
        out = analysis_service.advice(self.settings, self.course_id, "数字图像处理", llm=llm)
        self.assertTrue(out["ok"])
        prompt = llm.calls[0][1]["content"]
        self.assertIn("Canny", prompt)             # 错题原题
        self.assertIn("边缘检测", prompt)           # 知识点
        self.assertIn("正确率 0%", prompt)   # 1 次作答、0 次答对
        self.assertIn("3 条建议", llm.calls[0][0]["content"])

    def test_all_correct_still_generates(self):
        qs = self.make_questions()
        db.add_attempt(self.settings.db_path, qs[0].id, "A", True)
        out = analysis_service.advice(self.settings, self.course_id, "课", llm=FakeLLM())
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
