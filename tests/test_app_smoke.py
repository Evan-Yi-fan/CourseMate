"""用 Streamlit 官方 AppTest 真实执行 app.py，确认页面能渲染且不抛异常。

这比"打开浏览器看起来没报错"可靠：它会把脚本执行期的异常直接暴露出来。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch
from io import BytesIO
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from knowledge.retriever import reset_clients

APP = Path(__file__).resolve().parent.parent / "app.py"


class TestAppSmoke(unittest.TestCase):
    def setUp(self):
        # 首页会打开 ChromaDB，Windows 下会持有文件句柄，清理失败不应让测试报错
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        # 指向临时目录，避免污染项目 data/
        os.environ["DB_PATH"] = str(root / "test.db")
        os.environ["CHROMA_PATH"] = str(root / "chroma")
        os.environ["UPLOAD_DIR"] = str(root / "uploads")
        os.environ["LLM_API_KEY"] = ""
        os.environ["LLM_MODEL"] = ""
        # boot() 用了 st.cache_resource，会跨用例缓存 Settings；
        # 每个用例换了临时目录，必须清掉缓存，否则会连到上一个已删除的库。
        st.cache_resource.clear()

    def tearDown(self):
        for k in ("DB_PATH", "CHROMA_PATH", "UPLOAD_DIR", "LLM_API_KEY", "LLM_MODEL"):
            os.environ.pop(k, None)
        reset_clients()
        self.tmp.cleanup()

    def test_app_renders_without_exception(self):
        at = AppTest.from_file(str(APP), default_timeout=30).run()
        self.assertEqual(list(at.exception), [], f"页面抛异常: {at.exception}")
        self.assertTrue(len(at.title) >= 1)
        self.assertIn("CourseMate", at.title[0].value)

    def test_game_preview_without_course_or_llm(self):
        at = AppTest.from_file(str(APP), default_timeout=30).run()
        at.switch_page("pages/5_灵玉秘境.py").run()
        self.assertEqual(list(at.exception), [])
        at.button(key="lj_preview").click().run()
        self.assertEqual(list(at.exception), [])
        self.assertEqual(at.session_state["lj_stage"], "preview")
        self.assertTrue(any("初始灵玉为 30" in item.value for item in at.info))

    def test_course_card_switch_stays_selected_across_pages(self):
        from database import db
        db_path = Path(os.environ["DB_PATH"])
        db.init_db(db_path)
        first = db.create_course(db_path, "图像处理", "视觉课程")
        second = db.create_course(db_path, "数据结构", "算法课程")
        at = AppTest.from_file(str(APP), default_timeout=30).run()
        self.assertEqual(at.session_state["course_id"], second)
        at.button(key=f"choose_course_{first}").click().run()
        self.assertEqual(list(at.exception), [])
        self.assertEqual(at.session_state["course_id"], first)
        self.assertIn("图像处理", at.selectbox(key="course_select").value)
        at.switch_page("pages/1_课程知识库.py").run()
        self.assertEqual(list(at.exception), [])
        self.assertEqual(at.session_state["course_id"], first)

    def test_delete_current_course_then_last_course(self):
        from database import db
        db_path = Path(os.environ["DB_PATH"])
        db.init_db(db_path)
        first = db.create_course(db_path, "保留课程")
        second = db.create_course(db_path, "删除课程")
        at = AppTest.from_file(str(APP), default_timeout=30).run()
        self.assertTrue(at.button(key=f"delete_course_{second}").disabled)
        at.session_state["quiz_questions"] = [{"id": 999}]
        at.checkbox(key=f"confirm_delete_course_{second}").check().run()
        at.button(key=f"delete_course_{second}").click().run()
        self.assertEqual(list(at.exception), [])
        self.assertIsNone(db.get_course(db_path, second))
        self.assertEqual(at.session_state["course_id"], first)
        self.assertNotIn("quiz_questions", at.session_state)
        at.checkbox(key=f"confirm_delete_course_{first}").check().run()
        at.button(key=f"delete_course_{first}").click().run()
        self.assertEqual(list(at.exception), [])
        self.assertIsNone(at.session_state["course_id"])
        self.assertEqual(db.list_courses(db_path), [])

    def test_delete_document_from_knowledge_page(self):
        from config.settings import Settings
        from database import db
        from services.document_service import handle_upload
        settings = Settings(db_path=Path(os.environ["DB_PATH"]),
                            chroma_path=Path(os.environ["CHROMA_PATH"]),
                            upload_dir=Path(os.environ["UPLOAD_DIR"]),
                            embedding_provider="hash", embedding_model="hash-test", embedding_dim=256)
        settings.ensure_dirs()
        db.init_db(settings.db_path)
        cid = db.create_course(settings.db_path, "资料管理")
        result = handle_upload(settings, cid, "wrong.txt", "需要删除的错误资料".encode())
        did = result["document_id"]
        file = Path(db.get_document(settings.db_path, did)["file_path"])
        at = AppTest.from_file(str(APP), default_timeout=30).run()
        at.switch_page("pages/1_课程知识库.py").run()
        self.assertTrue(at.button(key=f"delete_document_{did}").disabled)
        at.checkbox(key=f"confirm_delete_document_{did}").check().run()
        at.button(key=f"delete_document_{did}").click().run()
        self.assertEqual(list(at.exception), [])
        self.assertIsNone(db.get_document(settings.db_path, did))
        self.assertFalse(file.exists())
        self.assertTrue(any("已删除资料" in message.value for message in at.success))

    def test_create_course_via_form(self):
        at = AppTest.from_file(str(APP), default_timeout=30).run()
        # 表单的语义是填完一起提交，中途 run() 会把未提交的输入丢掉，
        # 所以这里先填值再点提交，只跑一次。
        at.text_input[0].set_value("数字图像处理")
        self.assertEqual(len(at.text_area), 0)
        at.button[0].click().run()
        self.assertEqual(list(at.exception), [])
        joined = " ".join(m.value for m in at.success)
        self.assertIn("数字图像处理", joined)

    def _course_with_materials(self):
        from config.settings import Settings
        from database import db
        from services.document_service import handle_upload
        os.environ["LLM_API_KEY"] = "test-only-key"
        os.environ["LLM_MODEL"] = "test-model"
        settings = Settings(db_path=Path(os.environ["DB_PATH"]),
                            chroma_path=Path(os.environ["CHROMA_PATH"]),
                            upload_dir=Path(os.environ["UPLOAD_DIR"]),
                            embedding_provider="hash", embedding_model="hash-test", embedding_dim=256)
        settings.ensure_dirs()
        db.init_db(settings.db_path)
        cid = db.create_course(settings.db_path, "交互验证")
        ids = [handle_upload(settings, cid, name, "课程资料测试内容。".encode())["document_id"]
               for name in ("one.txt", "two.txt")]
        return cid, ids

    def test_qa_examples_fill_draft_without_sending(self):
        cid, _ = self._course_with_materials()
        at = AppTest.from_file(str(APP), default_timeout=30).run()
        at.switch_page("pages/2_AI智能问答.py").run()
        with patch("services.qa_service.QAService.ask") as ask:
            for index, text in enumerate(["帮我总结这些资料", "帮我找一下这个知识点的位置："]):
                at.button(key=f"qa_example_{index}").click().run()
                self.assertEqual(list(at.exception), [])
                self.assertTrue(at.chat_input[0].proto.set_value)
                self.assertEqual(at.chat_input[0].proto.value, text)
                self.assertEqual(at.session_state[f"qa_{cid}"], [])
            ask.assert_not_called()

    def test_both_quiz_pages_require_selection_and_support_select_all(self):
        cid, ids = self._course_with_materials()
        at = AppTest.from_file(str(APP), default_timeout=30).run()
        for page, prefix in [("pages/3_智能试题.py", "quiz"), ("pages/5_灵玉秘境.py", "lj")]:
            at.switch_page(page).run()
            self.assertEqual(list(at.exception), [])
            self.assertTrue(at.button(key=f"{prefix}_gen").disabled)
            at.checkbox(key=f"{prefix}_all_docs_{cid}").check().run()
            self.assertEqual(set(at.multiselect[0].value), set(ids))
            self.assertFalse(at.button(key=f"{prefix}_gen").disabled)
            at.checkbox(key=f"{prefix}_all_docs_{cid}").uncheck().run()
            self.assertEqual(at.multiselect[0].value, [])
            self.assertTrue(at.button(key=f"{prefix}_gen").disabled)
            at.multiselect[0].set_value([ids[0]]).run()
            self.assertFalse(at.checkbox(key=f"{prefix}_all_docs_{cid}").value)
            at.radio(key=f"{prefix}_type").set_value("判断题")
            at.number_input(key=f"{prefix}_count").set_value(2)
            with patch("services.quiz_service.QuizService.generate", return_value=[]) as generate:
                at.button(key=f"{prefix}_gen").click().run()
                self.assertEqual(list(at.exception), [])
                generate.assert_called_once_with(cid, count=2, question_type="judge", document_ids=[ids[0]])

    def test_game_adds_correct_answer_reward_to_initial_jade(self):
        from database import db
        from services.quiz_service import Question
        cid, ids = self._course_with_materials()
        qid = db.add_question(Path(os.environ["DB_PATH"]), cid, question="这是一道测试判断题吗？",
                              question_type="judge", options=[{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
                              answer="A", explanation="测试解析", knowledge_point="测试知识点")
        question = Question(id=qid, question="这是一道测试判断题吗？", question_type="judge",
                            options=[{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
                            answer="A", explanation="测试解析", knowledge_point="测试知识点")
        at = AppTest.from_file(str(APP), default_timeout=30).run()
        at.switch_page("pages/5_灵玉秘境.py").run()
        at.multiselect[0].set_value([ids[0]]).run()
        with patch("services.quiz_service.QuizService.generate", return_value=[question]):
            at.button(key="lj_gen").click().run()
        at.radio(key=f"lj_q_{qid}").set_value("A")
        next(b for b in at.button if b.label == "提交并进入秘境").click().run()
        self.assertEqual(list(at.exception), [])
        self.assertEqual(at.session_state["lj_stage"], "play")
        self.assertEqual(at.session_state["lj_reward"]["total"], 10)
        self.assertEqual(at.session_state["lj_jade"], 40)

    def test_successful_upload_resets_picker_and_keeps_result(self):
        cid, _ = self._course_with_materials()
        at = AppTest.from_file(str(APP), default_timeout=30).run()
        file = BytesIO("新的资料内容。".encode())
        file.name = "new.txt"
        with patch("streamlit.file_uploader", return_value=[file]) as uploader:
            at.switch_page("pages/1_课程知识库.py").run()
            with patch("services.document_service.handle_upload", return_value={"pages": 1, "chunks": 1}) as upload:
                next(b for b in at.button if b.label == "开始处理 1 个文件").click().run()
                upload.assert_called_once()
            self.assertEqual(list(at.exception), [])
            self.assertEqual(at.session_state[f"upload_version_{cid}"], 1)
            self.assertEqual(uploader.call_args.kwargs["key"], f"course_upload_{cid}_1")
            self.assertTrue(any("new.txt" in item.value and "已入库" in item.value for item in at.success))


if __name__ == "__main__":
    unittest.main(verbosity=2)
