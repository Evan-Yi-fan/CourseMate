"""配置与数据层的最小回归测试。

运行：.venv\\Scripts\\python.exe -m pytest tests -q   或   python -m unittest discover tests
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from config.settings import ConfigError, Settings, mask_secret
from database import db


class TestSettings(unittest.TestCase):
    def test_mask_secret_never_leaks_full_key(self):
        key = "sk-abcdefghijklmnopqrstuvwxyz123456"
        masked = mask_secret(key)
        self.assertNotIn(key, masked)
        self.assertTrue(masked.startswith("sk-a"))
        self.assertEqual(mask_secret(""), "(未配置)")
        self.assertEqual(mask_secret("ab"), "**")

    def test_missing_llm_fields_are_reported(self):
        s = Settings(llm_api_key="", llm_model="", llm_base_url="")
        self.assertFalse(s.llm_ready)
        self.assertEqual(s.llm_missing(), ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"])

    def test_overlap_must_be_smaller_than_chunk(self):
        s = Settings(chunk_size=100, chunk_overlap=100)
        with self.assertRaises(ConfigError):
            s.validate()

    def test_invalid_embedding_provider_rejected(self):
        with self.assertRaises(ConfigError):
            Settings(embedding_provider="magic").validate()

    def test_as_dict_masks_key(self):
        s = Settings(llm_api_key="sk-verysecretvalue1234567890")
        dumped = s.as_dict()
        self.assertNotIn("verysecret", str(dumped))


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init_db(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_creates_all_tables(self):
        counts = db.table_counts(self.db_path)
        self.assertEqual(set(counts), {"courses", "documents", "questions",
                                       "quiz_attempts", "chat_messages"})
        self.assertTrue(all(v == 0 for v in counts.values()))

    def test_create_and_list_course(self):
        cid = db.create_course(self.db_path, "数字图像处理", "课件与教材")
        self.assertGreater(cid, 0)
        courses = db.list_courses(self.db_path)
        self.assertEqual(len(courses), 1)
        self.assertEqual(courses[0]["name"], "数字图像处理")
        self.assertEqual(courses[0]["doc_count"], 0)

    def test_empty_course_name_rejected(self):
        with self.assertRaises(ValueError):
            db.create_course(self.db_path, "   ")

    def test_foreign_key_enforced(self):
        """直接插一条不存在的 course_id，应被外键约束拦下。"""
        import sqlite3

        with self.assertRaises(sqlite3.IntegrityError):
            with db.session(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO documents (course_id, filename, file_path, file_type, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (9999, "a.pdf", "/tmp/a.pdf", "pdf", db.now()),
                )

    def test_cascade_delete(self):
        cid = db.create_course(self.db_path, "临时课程")
        with db.session(self.db_path) as conn:
            conn.execute(
                "INSERT INTO questions (course_id, question, answer, created_at) VALUES (?,?,?,?)",
                (cid, "1+1=?", "2", db.now()),
            )
            conn.execute("DELETE FROM courses WHERE id = ?", (cid,))
        self.assertEqual(db.table_counts(self.db_path)["questions"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
