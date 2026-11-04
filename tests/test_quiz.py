"""阶段 D 的测试：JSON 校验、出题、判分、工具参数校验、意图路由。

重点测"程序侧是否守得住"，而不是模型答得好不好：
模型输出用 FakeLLM 造，异常输入用畸形 JSON 造。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent import tools as tools_mod
from agent.assistant import Assistant, parse_count, parse_question_type, route_by_rule
from config.settings import Settings
from database import db
from knowledge import retriever as retriever_mod
from services import document_service as docsvc
from services.llm_service import ChatResult
from services.quiz_service import (QuizError, QuizService, QuizValidationError,
                                   extract_json, grade_answer, grade_batch,
                                   validate_questions)

DOC = (
    "直方图均衡化通过累积分布函数把原始灰度映射到均匀分布，从而增强对比度。\n"
    "Canny 边缘检测包含高斯平滑、计算梯度、非极大值抑制、双阈值滞后连接四步。\n"
    "Otsu 方法自动选取使类间方差最大的阈值。"
)


def good_payload(count: int = 2, qtype: str = "single") -> dict:
    qs = []
    for i in range(count):
        if qtype == "single":
            qs.append({
                "question": f"第{i + 1}题：直方图均衡化的作用是什么？",
                "type": "single",
                "options": [{"key": "A", "text": "增强对比度"},
                            {"key": "B", "text": "压缩体积"},
                            {"key": "C", "text": "去噪声"},
                            {"key": "D", "text": "边缘检测"}],
                "answer": "A",
                "explanation": "均衡化把灰度映射到近似均匀分布，从而增强对比度。",
                "knowledge_point": "直方图",
            })
        else:
            qs.append({
                "question": f"第{i + 1}题：Canny 包含非极大值抑制。",
                "type": "judge",
                "options": [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
                "answer": "A",
                "explanation": "Canny 的第三步就是非极大值抑制。",
                "knowledge_point": "边缘检测",
            })
    return {"questions": qs}


class FakeLLM:
    def __init__(self, text: str):
        self.text = text
        self.calls: list[list[dict]] = []

    def chat(self, messages, **kwargs) -> ChatResult:
        self.calls.append(messages)
        return ChatResult(text=self.text, model="fake", latency_ms=1)


class TestJsonAndValidation(unittest.TestCase):
    def test_extract_json_with_fence_and_prose(self):
        text = '好的，这是题目：\n```json\n{"questions": []}\n```\n希望有帮助'
        self.assertEqual(extract_json(text), {"questions": []})

    def test_extract_json_rejects_non_json(self):
        with self.assertRaises(QuizValidationError):
            extract_json("抱歉，我无法完成这个任务。")

    def test_valid_single_choice(self):
        out = validate_questions(good_payload(2), 2, "single")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["answer"], "A")
        self.assertEqual(len(out[0]["options"]), 4)

    def test_count_mismatch_rejected(self):
        with self.assertRaises(QuizValidationError):
            validate_questions(good_payload(2), 3, "single")

    def test_wrong_option_count_rejected(self):
        payload = good_payload(1)
        payload["questions"][0]["options"] = payload["questions"][0]["options"][:3]
        with self.assertRaises(QuizValidationError):
            validate_questions(payload, 1, "single")

    def test_answer_not_in_options_rejected(self):
        payload = good_payload(1)
        payload["questions"][0]["answer"] = "Z"
        with self.assertRaises(QuizValidationError):
            validate_questions(payload, 1, "single")

    def test_type_mismatch_rejected(self):
        payload = good_payload(1, qtype="judge")
        with self.assertRaises(QuizValidationError):
            validate_questions(payload, 1, "single")

    def test_duplicate_option_keys_rejected(self):
        payload = good_payload(1)
        for o in payload["questions"][0]["options"]:
            o["key"] = "A"
        with self.assertRaises(QuizValidationError):
            validate_questions(payload, 1, "single")

    def test_judge_needs_two_options(self):
        payload = good_payload(1, qtype="judge")
        out = validate_questions(payload, 1, "judge")
        self.assertEqual(len(out[0]["options"]), 2)


class TestRouting(unittest.TestCase):
    def test_rule_matches_quiz_request(self):
        intent, args = route_by_rule("帮我出 5 道单选题")
        self.assertEqual(intent, "generate_quiz")
        self.assertEqual(args["count"], 5)
        self.assertEqual(args["question_type"], "single")

    def test_rule_matches_chinese_number(self):
        intent, args = route_by_rule("来三道判断题")
        self.assertEqual(args["count"], 3)
        self.assertEqual(args["question_type"], "judge")

    def test_rule_matches_mistakes(self):
        self.assertEqual(route_by_rule("看看我的错题和正确率")[0], "analyze_mistakes")

    def test_plain_question_not_matched(self):
        self.assertIsNone(route_by_rule("Canny 边缘检测包含哪几步"))

    def test_parse_count_defaults(self):
        self.assertEqual(parse_count("出几道题"), 3)
        self.assertEqual(parse_count("出 20 道题"), 10)      # 上限截断
        self.assertEqual(parse_question_type("判断题"), "judge")


class QuizTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.settings = Settings(
            db_path=root / "t.db", chroma_path=root / "chroma", upload_dir=root / "up",
            embedding_provider="hash", embedding_model="hash-test", embedding_dim=256,
            qa_min_score=0.0,
        )
        self.settings.ensure_dirs()
        db.init_db(self.settings.db_path)
        self.course_id = db.create_course(self.settings.db_path, "数字图像处理")
        docsvc.handle_upload(self.settings, self.course_id, "note.txt", DOC.encode("utf-8"))

    def tearDown(self):
        retriever_mod.reset_clients()
        self.tmp.cleanup()


class TestGenerateAndGrade(QuizTestBase):
    def test_selected_documents_exclude_unselected_material(self):
        included = docsvc.handle_upload(self.settings, self.course_id, "chosen.txt", "所选文件独有内容：光合作用。".encode())["document_id"]
        llm = FakeLLM(json.dumps(good_payload(1), ensure_ascii=False))
        QuizService(self.settings, llm).generate(self.course_id, count=1, document_ids=[included])
        prompt = llm.calls[0][1]["content"]
        self.assertIn("光合作用", prompt)
        self.assertNotIn("直方图均衡化通过", prompt)
        self.assertNotIn("note.txt", prompt)

    def test_multiple_selected_documents_are_all_covered(self):
        extra = docsvc.handle_upload(self.settings, self.course_id, "extra.txt", "第二份资料内容：二叉树。".encode())["document_id"]
        original = next(d["id"] for d in db.list_documents(self.settings.db_path, self.course_id) if d["filename"] == "note.txt")
        llm = FakeLLM(json.dumps(good_payload(1), ensure_ascii=False))
        QuizService(self.settings, llm).generate(self.course_id, count=1, document_ids=[original, extra])
        prompt = llm.calls[0][1]["content"]
        self.assertIn("note.txt", prompt)
        self.assertIn("extra.txt", prompt)
        self.assertIn("二叉树", prompt)

    def test_empty_selection_is_rejected_before_model_call(self):
        llm = FakeLLM("unused")
        with self.assertRaises(QuizError):
            QuizService(self.settings, llm).generate(self.course_id, document_ids=[])
        self.assertEqual(llm.calls, [])

    def test_other_course_document_is_rejected(self):
        other = db.create_course(self.settings.db_path, "另一门课")
        foreign = docsvc.handle_upload(self.settings, other, "foreign.txt", "其他课程资料内容。".encode())["document_id"]
        llm = FakeLLM("unused")
        with self.assertRaises(QuizError):
            QuizService(self.settings, llm).generate(self.course_id, document_ids=[foreign])
        self.assertEqual(llm.calls, [])

    def test_generate_saves_questions(self):
        llm = FakeLLM(json.dumps(good_payload(2), ensure_ascii=False))
        questions = QuizService(self.settings, llm=llm).generate(
            self.course_id, count=2, question_type="single"
        )
        self.assertEqual(len(questions), 2)
        self.assertTrue(all(q.id > 0 for q in questions))
        self.assertEqual(len(db.list_questions(self.settings.db_path, self.course_id)), 2)
        # 出题 Prompt 里必须带上真实资料，否则就是凭空出题
        prompt = llm.calls[0][1]["content"]
        self.assertIn("【资料片段】", prompt)
        self.assertIn("直方图", prompt)

    def test_generate_retries_then_succeeds(self):
        bad = '{"questions": []}'
        good = json.dumps(good_payload(1), ensure_ascii=False)

        class RetryLLM:
            def __init__(self):
                self.n = 0

            def chat(self, messages, **kwargs):
                self.n += 1
                return ChatResult(text=bad if self.n == 1 else good, model="fake", latency_ms=1)

        questions = QuizService(self.settings, llm=RetryLLM()).generate(
            self.course_id, count=1, question_type="single", retries=1
        )
        self.assertEqual(len(questions), 1)

    def test_generate_fails_after_retry(self):
        llm = FakeLLM("这不是 JSON")
        with self.assertRaises(QuizError):
            QuizService(self.settings, llm=llm).generate(
                self.course_id, count=1, question_type="single", retries=1
            )
        self.assertEqual(len(llm.calls), 2)          # 原始 + 重试一次

    def test_grade_correct_and_wrong(self):
        llm = FakeLLM(json.dumps(good_payload(1), ensure_ascii=False))
        q = QuizService(self.settings, llm=llm).generate(
            self.course_id, count=1, question_type="single")[0]

        r1 = grade_answer(self.settings, q.id, "A")
        self.assertTrue(r1.is_correct)
        r2 = grade_answer(self.settings, q.id, "B")
        self.assertFalse(r2.is_correct)
        self.assertEqual(r2.correct_answer, "A")

    def test_grade_batch_and_stats(self):
        llm = FakeLLM(json.dumps(good_payload(2), ensure_ascii=False))
        qs = QuizService(self.settings, llm=llm).generate(
            self.course_id, count=2, question_type="single")

        result = grade_batch(self.settings, {qs[0].id: "A", qs[1].id: "B"})
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["correct"], 1)
        self.assertEqual(result["score"], 50.0)

        stats = db.attempt_stats(self.settings.db_path, self.course_id)
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["by_knowledge"][0]["knowledge_point"], "直方图")

    def test_grade_missing_question(self):
        with self.assertRaises(QuizError):
            grade_answer(self.settings, 99999, "A")


class TestToolValidation(QuizTestBase):
    def test_unknown_tool(self):
        with self.assertRaises(tools_mod.ToolError):
            tools_mod.run_tool("drop_database", self.settings, self.course_id, {})

    def test_count_out_of_range(self):
        with self.assertRaises(tools_mod.ToolError):
            tools_mod.generate_quiz(self.settings, self.course_id, count=99)

    def test_bad_question_type(self):
        with self.assertRaises(tools_mod.ToolError):
            tools_mod.generate_quiz(self.settings, self.course_id, count=2,
                                    question_type="essay")

    def test_empty_query(self):
        with self.assertRaises(tools_mod.ToolError):
            tools_mod.knowledge_search(self.settings, self.course_id, "   ")

    def test_unknown_course(self):
        with self.assertRaises(tools_mod.ToolError):
            tools_mod.analyze_mistakes(self.settings, 424242)

    def test_analyze_mistakes_without_attempts(self):
        out = tools_mod.analyze_mistakes(self.settings, self.course_id)
        self.assertEqual(out["total"], 0)
        self.assertIn("还没有答题记录", out["summary"])


class TestAssistantRouting(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.assistant = Assistant(self.settings, llm=FakeLLM('{"intent": "knowledge_qa"}'))

    def test_rule_route_skips_llm(self):
        intent, args, routed_by = self.assistant.route("帮我出 4 道题")
        self.assertEqual(intent, "generate_quiz")
        self.assertEqual(args["count"], 4)
        self.assertEqual(routed_by, "rule")
        self.assertEqual(self.assistant.llm.calls, [])   # 规则命中就不该调模型

    def test_llm_route(self):
        assistant = Assistant(self.settings, llm=FakeLLM('{"intent": "analyze_mistakes", "args": {}}'))
        intent, _, routed_by = assistant.route("我最近学得怎么样")
        self.assertEqual(intent, "analyze_mistakes")
        self.assertEqual(routed_by, "llm")

    def test_bad_llm_json_falls_back_to_qa(self):
        assistant = Assistant(self.settings, llm=FakeLLM("我猜你想问知识"))
        intent, args, routed_by = assistant.route("傅里叶变换是什么")
        self.assertEqual(intent, "knowledge_qa")
        self.assertEqual(routed_by, "fallback")
        self.assertEqual(args["query"], "傅里叶变换是什么")


if __name__ == "__main__":
    unittest.main(verbosity=2)
