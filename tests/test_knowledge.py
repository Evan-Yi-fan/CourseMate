"""阶段 B 的回归测试：解析、分块、建索引、检索、异常路径。

检索测试刻意用 hash 向量后端：它确定性、零依赖、不下载模型，
适合验证"写入/查询/持久化/清理"这套逻辑，而不是验证语义质量。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config.settings import Settings
from database import db
from knowledge import parser as parser_mod
from knowledge.embeddings import HashEmbedder
from knowledge.retriever import CourseIndex, reset_clients
from knowledge.splitter import split_pages
from services import document_service as docsvc


def make_settings(tmp: Path) -> Settings:
    return Settings(
        db_path=tmp / "t.db",
        chroma_path=tmp / "chroma",
        upload_dir=tmp / "uploads",
        embedding_provider="hash",
        embedding_model="hash-test",
        embedding_dim=256,
        chunk_size=120,
        chunk_overlap=20,
    )


class TestParser(unittest.TestCase):
    def setUp(self):
        # Windows 下 Chroma 会持有文件句柄，清理失败不应让测试报错
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        reset_clients()
        self.tmp.cleanup()

    def test_txt_parses(self):
        p = self.dir / "a.txt"
        p.write_text("第一段内容。\n第二段内容。", encoding="utf-8")
        pages = parser_mod.parse_file(p)
        self.assertEqual(len(pages), 1)
        self.assertIsNone(pages[0].page)
        self.assertIn("第一段", pages[0].text)

    def test_unsupported_extension_rejected(self):
        p = self.dir / "a.md"
        p.write_text("hello", encoding="utf-8")
        with self.assertRaises(parser_mod.ParseError) as ctx:
            parser_mod.parse_file(p)
        self.assertIn("不支持", str(ctx.exception))

    def test_empty_file_rejected(self):
        p = self.dir / "empty.txt"
        p.write_bytes(b"   ")
        with self.assertRaises(parser_mod.ParseError):
            parser_mod.parse_file(p)

    def test_broken_pdf_gives_friendly_error(self):
        p = self.dir / "broken.pdf"
        p.write_bytes(b"%PDF-1.4 not really a pdf")
        with self.assertRaises(parser_mod.ParseError):
            parser_mod.parse_file(p)

    def test_real_sample_pdf_keeps_page_numbers(self):
        sample = Path(__file__).resolve().parent.parent / "samples" / "数字图像处理_课件.pdf"
        if not sample.exists():
            self.skipTest("样例 PDF 不存在，先运行 scripts/make_sample_docs.py")
        pages = parser_mod.parse_file(sample)
        self.assertEqual([p.page for p in pages], [1, 2, 3, 4, 5])
        self.assertIn("直方图", pages[1].text)


class TestSplitter(unittest.TestCase):
    def test_short_text_single_chunk(self):
        pages = [parser_mod.PageText(page=1, text="很短的一段话。")]
        chunks = split_pages(pages, chunk_size=600, overlap=100)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].page, 1)

    def test_long_text_respects_size_and_overlap(self):
        text = "这是一个用来测试分块的句子。" * 60          # 约 780 字
        pages = [parser_mod.PageText(page=2, text=text)]
        chunks = split_pages(pages, chunk_size=120, overlap=20)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c.text), 120)
            self.assertEqual(c.page, 2)
        self.assertEqual([c.chunk_index for c in chunks], list(range(len(chunks))))

    def test_overlap_must_be_smaller(self):
        with self.assertRaises(ValueError):
            split_pages([parser_mod.PageText(1, "x" * 100)], 100, 100)

    def test_pages_are_not_merged(self):
        pages = [parser_mod.PageText(1, "第一页内容。"), parser_mod.PageText(2, "第二页内容。")]
        chunks = split_pages(pages, 600, 100)
        self.assertEqual({c.page for c in chunks}, {1, 2})


class TestIndex(unittest.TestCase):
    def setUp(self):
        # Windows 下 Chroma 会持有文件句柄，清理失败不应让测试报错
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.settings = make_settings(Path(self.tmp.name))
        self.settings.ensure_dirs()
        db.init_db(self.settings.db_path)
        self.course_id = db.create_course(self.settings.db_path, "测试课程")
        self.emb = HashEmbedder(256)

    def tearDown(self):
        reset_clients()
        self.tmp.cleanup()

    def test_add_and_search(self):
        idx = CourseIndex(self.settings, self.course_id)
        chunks = split_pages([parser_mod.PageText(3, "傅里叶变换把图像转换到频域。")], 600, 100)
        n = idx.add_chunks(chunks, document_id=1, filename="a.pdf", embedder=self.emb)
        self.assertEqual(n, 1)
        hits = idx.search("傅里叶变换", self.emb, top_k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0].page, 3)
        self.assertEqual(hits[0].filename, "a.pdf")

    def test_reupload_does_not_duplicate(self):
        idx = CourseIndex(self.settings, self.course_id)
        chunks = split_pages([parser_mod.PageText(1, "重复上传测试。")], 600, 100)
        idx.add_chunks(chunks, document_id=7, filename="a.pdf", embedder=self.emb)
        idx.add_chunks(chunks, document_id=7, filename="a.pdf", embedder=self.emb)
        self.assertEqual(idx.count(), 1)

    def test_delete_document(self):
        idx = CourseIndex(self.settings, self.course_id)
        chunks = split_pages([parser_mod.PageText(1, "待删除内容。")], 600, 100)
        idx.add_chunks(chunks, document_id=9, filename="b.pdf", embedder=self.emb)
        idx.delete_document(9)
        self.assertEqual(idx.count(), 0)

    def test_persistence_across_instances(self):
        chunks = split_pages([parser_mod.PageText(2, "重启后仍应能检索到。")], 600, 100)
        CourseIndex(self.settings, self.course_id).add_chunks(
            chunks, document_id=3, filename="c.pdf", embedder=self.emb
        )
        # 新建实例模拟重启
        fresh = CourseIndex(self.settings, self.course_id)
        self.assertEqual(fresh.count(), 1)
        self.assertTrue(fresh.search("重启", self.emb, top_k=1))

    def test_courses_are_isolated(self):
        other = db.create_course(self.settings.db_path, "另一门课")
        chunks = split_pages([parser_mod.PageText(1, "只属于课程一。")], 600, 100)
        CourseIndex(self.settings, self.course_id).add_chunks(
            chunks, document_id=1, filename="a.pdf", embedder=self.emb
        )
        self.assertEqual(CourseIndex(self.settings, other).count(), 0)


class TestUploadValidation(unittest.TestCase):
    def setUp(self):
        # Windows 下 Chroma 会持有文件句柄，清理失败不应让测试报错
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.settings = make_settings(Path(self.tmp.name))

    def tearDown(self):
        reset_clients()
        self.tmp.cleanup()

    def test_reject_unsupported_type(self):
        with self.assertRaises(docsvc.UploadError) as ctx:
            docsvc.validate_upload(self.settings, "a.exe", 100)
        self.assertIn("不支持", str(ctx.exception))

    def test_reject_oversize(self):
        with self.assertRaises(docsvc.UploadError) as ctx:
            docsvc.validate_upload(self.settings, "a.pdf", 60 * 1024 * 1024)
        self.assertIn("超过", str(ctx.exception))

    def test_filename_path_traversal_is_stripped(self):
        self.assertEqual(docsvc.safe_filename("../../etc/passwd.txt"), "passwd.txt")
        self.assertEqual(docsvc.safe_filename(r"C:\Windows\evil.pdf"), "evil.pdf")
        cleaned = docsvc.safe_filename("中文 名字(1).pdf")
        self.assertNotIn(" ", cleaned)
        self.assertNotIn("(", cleaned)
        self.assertTrue(cleaned.endswith(".pdf"))


class TestIngestFlow(unittest.TestCase):
    def setUp(self):
        # Windows 下 Chroma 会持有文件句柄，清理失败不应让测试报错
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.settings = make_settings(Path(self.tmp.name))
        self.settings.ensure_dirs()
        db.init_db(self.settings.db_path)
        self.course_id = db.create_course(self.settings.db_path, "测试课程")

    def tearDown(self):
        reset_clients()
        self.tmp.cleanup()

    def test_upload_txt_end_to_end(self):
        data = "卷积是线性滤波的核心运算。中值滤波对椒盐噪声有效。".encode("utf-8")
        result = docsvc.handle_upload(self.settings, self.course_id, "note.txt", data)
        self.assertEqual(result["chunks"], 1)
        docs = db.list_documents(self.settings.db_path, self.course_id)
        self.assertEqual(docs[0]["status"], "ready")
        self.assertEqual(docs[0]["chunk_count"], 1)

    def test_reupload_same_name_replaces_instead_of_duplicating(self):
        data = "卷积是线性滤波的核心运算。".encode("utf-8")
        first = docsvc.handle_upload(self.settings, self.course_id, "note.txt", data)
        second = docsvc.handle_upload(self.settings, self.course_id, "note.txt", data)

        self.assertFalse(first["replaced"])
        self.assertTrue(second["replaced"])
        self.assertEqual(first["document_id"], second["document_id"])
        # 只应有一条文档记录，向量也不翻倍（任务书 §5.3）
        self.assertEqual(len(db.list_documents(self.settings.db_path, self.course_id)), 1)
        self.assertEqual(CourseIndex(self.settings, self.course_id).count(), 1)

    def test_reupload_updated_content_keeps_single_record(self):
        v1 = "旧内容：均值滤波。".encode("utf-8")
        v2 = "新内容：中值滤波对椒盐噪声有效。".encode("utf-8")
        docsvc.handle_upload(self.settings, self.course_id, "note.txt", v1)
        r2 = docsvc.handle_upload(self.settings, self.course_id, "note.txt", v2)
        self.assertTrue(r2["replaced"])
        self.assertEqual(len(db.list_documents(self.settings.db_path, self.course_id)), 1)

        hits = CourseIndex(self.settings, self.course_id).search(
            "中值滤波", HashEmbedder(256), 3)
        self.assertTrue(any("中值滤波" in h.text for h in hits))

    def test_failed_parse_marks_document_failed(self):
        with self.assertRaises(Exception):
            docsvc.handle_upload(self.settings, self.course_id, "bad.pdf", b"%PDF-1.4 broken")
        docs = db.list_documents(self.settings.db_path, self.course_id)
        self.assertEqual(docs[0]["status"], "failed")
        self.assertTrue(docs[0]["error"])
        # 失败不能留下空向量
        self.assertEqual(CourseIndex(self.settings, self.course_id).count(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
