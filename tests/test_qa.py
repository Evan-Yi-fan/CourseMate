"""阶段 C 的测试：拒答阈值、引用解析、Prompt 组装、问答落库。

模型用假的（FakeLLM），检索向量用 hash 后端——
这样测的是"我们的逻辑对不对"，而不是"模型答得好不好"，也让测试跑得快、可离线。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.prompts import NO_EVIDENCE_ANSWER, format_context
from config.settings import Settings
from database import db
from knowledge import retriever as retriever_mod
from knowledge.retriever import CourseIndex
from knowledge.embeddings import HashEmbedder
from services.llm_service import ChatResult
from services.qa_service import QAService, parse_citations
from services import document_service as docsvc

DOC = (
    "直方图均衡化通过累积分布函数把原始灰度映射到均匀分布，从而增强对比度。\n"
    "Canny 边缘检测包含高斯平滑、计算梯度、非极大值抑制、双阈值滞后连接四步。\n"
    "PSNR 衡量重建图像与原图的差异，SSIM 从亮度、对比度和结构三方面比较。"
)


class FakeLLM:
    """记录收到的 messages，返回预置回答。"""

    def __init__(self, text: str = "直方图均衡化用累积分布函数做映射 [1]。"):
        self.text = text
        self.received: list[list[dict[str, str]]] = []

    def chat(self, messages, **kwargs) -> ChatResult:
        self.received.append(messages)
        return ChatResult(text=self.text, model="fake-model", latency_ms=1)


class TestCitationParsing(unittest.TestCase):
    def test_extracts_and_sorts(self):
        self.assertEqual(parse_citations("结论 A [2]，结论 B [1]。", 3), [1, 2])

    def test_drops_out_of_range(self):
        # 模型编了一个不存在的 [7]，必须丢掉
        self.assertEqual(parse_citations("结论 [7] 和 [1]", 2), [1])

    def test_no_citation(self):
        self.assertEqual(parse_citations("没有引用", 3), [])


class TestContextFormatting(unittest.TestCase):
    def test_context_contains_number_and_page(self):
        from knowledge.retriever import Hit

        hits = [
            Hit(text="片段一内容", filename="课件.pdf", page=2, score=0.8,
                document_id=1, chunk_index=0),
            Hit(text="片段二内容", filename="笔记.txt", page=None, score=0.7,
                document_id=2, chunk_index=3),
        ]
        ctx = format_context(hits)
        self.assertIn("[1] 来源：课件.pdf 第 2 页", ctx)
        self.assertIn("[2] 来源：笔记.txt", ctx)
        self.assertNotIn("第 None 页", ctx)


class TestQAService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.settings = Settings(
            db_path=Path(self.tmp.name) / "t.db",
            chroma_path=Path(self.tmp.name) / "chroma",
            upload_dir=Path(self.tmp.name) / "up",
            embedding_provider="hash",
            embedding_model="hash-test",
            embedding_dim=256,
            qa_min_score=0.0,      # 默认不拒答，单独的用例再调阈值
            qa_top_k=3,
        )
        self.settings.ensure_dirs()
        db.init_db(self.settings.db_path)
        self.course_id = db.create_course(self.settings.db_path, "数字图像处理")
        docsvc.handle_upload(self.settings, self.course_id, "note.txt", DOC.encode("utf-8"))
        self.llm = FakeLLM()
        self.qa = QAService(self.settings, llm=self.llm)

    def tearDown(self):
        retriever_mod.reset_clients()
        self.tmp.cleanup()

    def test_answer_with_sources(self):
        r = self.qa.ask(self.course_id, "直方图均衡化怎么做")
        self.assertFalse(r.refused)
        self.assertTrue(r.sources)
        self.assertEqual(r.cited, [1])
        self.assertIn("直方图均衡化", r.answer)

    def test_prompt_contains_retrieved_evidence(self):
        self.qa.ask(self.course_id, "Canny 边缘检测有哪几步")
        messages = self.llm.received[-1]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("只使用", messages[0]["content"])
        user_prompt = messages[1]["content"]
        self.assertIn("【资料片段】", user_prompt)
        self.assertIn("Canny", user_prompt)

    def test_refuse_when_score_below_threshold(self):
        r = self.qa.ask(self.course_id, "直方图均衡化", min_score=0.999)
        self.assertTrue(r.refused)
        self.assertTrue(r.reason.startswith("检索到 1"), r.reason)
        self.assertEqual(r.answer, NO_EVIDENCE_ANSWER)
        # 拒答时不得调用模型，否则又变成让模型自由发挥
        self.assertEqual(self.llm.received, [])


    def test_model_side_refusal_is_marked(self):
        """片段相关但不足以作答时，模型会说"资料中没有"，此时也要标记为拒答。"""
        self.llm.text = "当前课程资料中没有找到足够依据。现有片段没有提到量化表数值 [1]。"
        r = self.qa.ask(self.course_id, "JPEG 量化表第一个元素是多少")
        self.assertTrue(r.refused)
        self.assertIn("没有答案", r.reason)
        # 片段仍然返回，方便用户自己判断
        self.assertTrue(r.sources)

    def test_empty_question_rejected(self):
        with self.assertRaises(ValueError):
            self.qa.ask(self.course_id, "   ")

    def test_history_persisted(self):
        self.qa.ask(self.course_id, "直方图均衡化怎么做")
        msgs = db.list_chat_messages(self.settings.db_path, self.course_id)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[1]["role"], "assistant")
        self.assertTrue(msgs[1]["sources"])

    def test_other_course_has_no_evidence(self):
        other = db.create_course(self.settings.db_path, "空课程")
        r = self.qa.ask(other, "直方图均衡化")
        self.assertTrue(r.refused)
        self.assertEqual(r.sources, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
