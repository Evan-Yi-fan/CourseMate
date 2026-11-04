"""演示文稿解析与知识库入库回归，测试使用本地构造的课件。"""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches

from config.settings import Settings
from database import db
from knowledge import parser
from knowledge.embeddings import HashEmbedder
from knowledge.retriever import CourseIndex, reset_clients
from services import document_service


def make_deck() -> Presentation:
    deck = Presentation()
    first = deck.slides.add_slide(deck.slide_layouts[6])
    first.shapes.add_textbox(Inches(1), Inches(.3), Inches(6), Inches(1)).text = "直方图均衡化用于增强图像对比度。"
    group = first.shapes.add_group_shape()
    group.shapes.add_textbox(Inches(1), Inches(1.5), Inches(4), Inches(1)).text = "组合图形中的卷积与滤波知识。"
    table = first.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
    table.cell(0, 0).text = "方法"
    table.cell(0, 1).text = "用途"
    table.cell(1, 0).text = "中值滤波"
    table.cell(1, 1).text = "抑制椒盐噪声"
    first.notes_slide.notes_text_frame.text = "备注补充：应保留边缘细节。"
    data = CategoryChartData()
    data.categories = ["练习前", "练习后"]
    data.add_series("正确率", [40, 80])
    first.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(5), Inches(2), Inches(3), Inches(2), data)
    deck.slides.add_slide(deck.slide_layouts[6])  # 保留真实空白第二页
    third = deck.slides.add_slide(deck.slide_layouts[6])
    third.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text = "Canny 边缘检测包含高斯平滑和双阈值处理。"
    return deck


def deck_bytes(deck=None) -> bytes:
    stream = io.BytesIO()
    (deck or make_deck()).save(stream)
    return stream.getvalue()


class TestPowerPoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.path = self.root / "讲义.pptx"
        self.path.write_bytes(deck_bytes())

    def tearDown(self):
        reset_clients()
        self.tmp.cleanup()

    def test_keeps_slide_numbers_across_blank_slide(self):
        pages = parser.parse_file(self.path)
        self.assertEqual([p.page for p in pages], [1, 3])
        self.assertIn("Canny", pages[1].text)

    def test_tables_groups_notes_and_charts_are_searchable_text(self):
        text = parser.parse_file(self.path)[0].text
        for expected in ("中值滤波 | 抑制椒盐噪声", "组合图形中的卷积", "备注补充", "练习后: 80", "正确率"):
            self.assertIn(expected, text)

    def test_merged_table_cells_are_not_duplicated(self):
        deck = make_deck()
        table = next(shape.table for shape in deck.slides[0].shapes if shape.has_table)
        cell = table.cell(0, 0)
        cell.merge(table.cell(0, 1))
        cell.text = "合并表头知识点"
        deck.save(self.path)
        self.assertEqual(parser.parse_file(self.path)[0].text.count("合并表头知识点"), 1)

    def test_uses_presentation_order_not_xml_filename(self):
        deck = make_deck()
        ids = deck.slides._sldIdLst
        last = ids[-1]
        ids.remove(last)
        ids.insert(0, last)
        deck.save(self.path)
        pages = parser.parse_file(self.path)
        self.assertEqual([p.page for p in pages], [1, 2])
        self.assertIn("Canny", pages[0].text)
        self.assertIn("直方图", pages[1].text)

    def test_empty_presentation_reports_no_text(self):
        deck = Presentation()
        deck.slides.add_slide(deck.slide_layouts[6])
        deck.save(self.path)
        with self.assertRaises(parser.NoTextError):
            parser.parse_file(self.path)

    def test_broken_pptx_reports_parse_error(self):
        self.path.write_bytes(b"not an office package")
        with self.assertRaises(parser.ParseError):
            parser.parse_file(self.path)

    def test_uppercase_extension(self):
        target = self.root / "LECTURE.PPTX"
        target.write_bytes(self.path.read_bytes())
        self.assertEqual(parser.parse_file(target)[1].page, 3)

    def test_both_presentation_extensions_pass_upload_validation(self):
        settings = Settings()
        self.assertEqual(document_service.validate_upload(settings, "课件.PPT", 100), ".ppt")
        self.assertEqual(document_service.validate_upload(settings, "课件.PPTX", 100), ".pptx")

    def test_renaming_pptx_to_ppt_is_rejected(self):
        target = self.root / "fake.ppt"
        target.write_bytes(self.path.read_bytes())
        with self.assertRaisesRegex(parser.ParseError, "不要只修改扩展名"):
            parser.parse_file(target)

    @unittest.skipUnless(sys.platform == "win32", "Windows旧版PPT转换分支")
    def test_legacy_conversion_failure_is_actionable(self):
        target = self.root / "old.ppt"
        target.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"test")
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(parser.ParseError, "PowerPoint"):
                parser.parse_file(target)

    @unittest.skipUnless(sys.platform == "win32", "Windows旧版PPT转换分支")
    def test_legacy_conversion_timeout_is_bounded(self):
        target = self.root / "old.ppt"
        target.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"test")
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 60)) as run:
            with self.assertRaisesRegex(parser.ParseError, "超时"):
                parser.parse_file(target)
            self.assertEqual(run.call_args.kwargs["timeout"], 60)

    def test_upload_retrieval_citations_and_replacement(self):
        settings = Settings(db_path=self.root / "test.db", chroma_path=self.root / "chroma",
                            upload_dir=self.root / "up", embedding_provider="hash",
                            embedding_model="hash-test", embedding_dim=256)
        settings.ensure_dirs()
        db.init_db(settings.db_path)
        cid = db.create_course(settings.db_path, "图像处理")
        first = document_service.handle_upload(settings, cid, "课件.pptx", self.path.read_bytes())
        self.assertEqual(first["pages"], 2)
        records = db.list_documents(settings.db_path, cid)
        self.assertEqual((records[0]["file_type"], records[0]["status"]), ("pptx", "ready"))
        index = CourseIndex(settings, cid)
        hits = index.search("Canny", HashEmbedder(256), top_k=10)
        self.assertTrue(any(hit.page == 3 and hit.filename == "课件.pptx" and "Canny" in hit.text for hit in hits))
        count = index.count()
        second = document_service.handle_upload(settings, cid, "课件.pptx", self.path.read_bytes())
        self.assertTrue(second["replaced"])
        self.assertEqual(first["document_id"], second["document_id"])
        self.assertEqual(len(db.list_documents(settings.db_path, cid)), 1)
        self.assertEqual(index.count(), count)

