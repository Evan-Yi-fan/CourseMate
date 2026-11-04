"""文档解析：PDF / DOCX / TXT / PPTX / PPT → [(页码, 文本), ...]。

设计原则：
1. 只做文本提取，绝不执行文档里的宏或代码（任务书 §11）；
2. 页码必须是 PDF 的真实物理页序（从 1 开始），因为它会出现在引用里给用户核对；
3. 提取不到文本时明确报错，而不是悄悄建一个空索引。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


class ParseError(RuntimeError):
    """文档损坏、加密、格式不支持等。"""


class NoTextError(ParseError):
    """文件结构正常，但提取不到任何可用文本（典型：扫描版 PDF）。"""


@dataclass
class PageText:
    page: int | None      # PDF/PPT为物理页序或幻灯片序号，DOCX/TXT为None
    text: str


def _parse_pdf(path: Path) -> list[PageText]:
    try:
        import pymupdf  # PyMuPDF 2.x 的推荐导入名
    except ImportError:  # 兼容旧版
        import fitz as pymupdf  # type: ignore

    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        raise ParseError(f"PDF 打开失败，文件可能已损坏：{type(exc).__name__}") from exc

    try:
        if getattr(doc, "needs_pass", False):
            raise ParseError("该 PDF 已加密，无法读取内容。")
        pages: list[PageText] = []
        for index, page in enumerate(doc, start=1):
            try:
                text = page.get_text("text") or ""
            except Exception:
                log.warning("第 %d 页文本提取失败，已跳过", index)
                continue
            text = text.strip()
            if text:
                pages.append(PageText(page=index, text=text))
        if not pages:
            raise NoTextError(
                "这份 PDF 提取不到任何文字，可能是扫描版或纯图片。"
                "本项目不含 OCR，请改用可复制文字的 PDF。"
            )
        log.info("PDF 解析完成 %s：%d 页含文本", path.name, len(pages))
        return pages
    finally:
        doc.close()


def _parse_docx(path: Path) -> list[PageText]:
    try:
        import docx
    except ImportError as exc:
        raise ParseError("缺少 python-docx，无法解析 DOCX") from exc

    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise ParseError(f"DOCX 打开失败，文件可能已损坏：{type(exc).__name__}") from exc

    blocks: list[str] = []
    for para in document.paragraphs:
        t = para.text.strip()
        if t:
            blocks.append(t)
    # 表格里的内容往往就是考点，必须收进来
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))

    text = "\n".join(blocks).strip()
    if not text:
        raise NoTextError("这份 DOCX 里没有可用文字。")
    log.info("DOCX 解析完成 %s：%d 段", path.name, len(blocks))
    return [PageText(page=None, text=text)]


def _parse_txt(path: Path) -> list[PageText]:
    raw = path.read_bytes()
    if not raw.strip():
        raise NoTextError("文件是空的。")
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            text = raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
        if text:
            log.info("TXT 解析完成 %s：编码 %s，%d 字", path.name, encoding, len(text))
            return [PageText(page=None, text=text)]
    raise ParseError("无法识别文件编码，请另存为 UTF-8 后重试。")


def _slide_shape_text(shapes) -> list[str]:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    blocks: list[str] = []
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            blocks.extend(_slide_shape_text(shape.shapes))
        elif shape.has_text_frame:
            text = shape.text_frame.text.replace("\v", "\n").strip()
            if text:
                blocks.append(text)
        elif shape.has_table:
            for row in shape.table.rows:
                # 合并单元格只读取原点，避免把同一段考点重复入库。
                values = [cell.text.strip() for cell in row.cells if not cell.is_spanned and cell.text.strip()]
                if values:
                    blocks.append(" | ".join(values))
        elif shape.has_chart:
            chart = shape.chart
            if chart.has_title and chart.chart_title.has_text_frame:
                blocks.append(chart.chart_title.text_frame.text)
            for plot in chart.plots:
                try:
                    categories = [str(category.label) for category in plot.categories]
                except (AttributeError, ValueError):
                    categories = []
                for series in plot.series:
                    values = list(series.values)
                    pairs = [f"{categories[i] if i < len(categories) else i + 1}: {value}"
                             for i, value in enumerate(values) if value is not None]
                    if pairs:
                        blocks.append(str(series.name) + "：" + "；".join(pairs))
    return blocks


def _parse_pptx(path: Path) -> list[PageText]:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise ParseError("缺少 python-pptx，请按 requirements.txt 安装依赖。") from exc
    try:
        presentation = Presentation(str(path))
        pages: list[PageText] = []
        # 使用slides的真实顺序，不能按slide1.xml等文件名排序；跳过空页也不能重编号。
        for number, slide in enumerate(presentation.slides, start=1):
            blocks = _slide_shape_text(slide.shapes)
            if slide.has_notes_slide:
                frame = slide.notes_slide.notes_text_frame
                notes = frame.text.strip() if frame is not None else ""
                if notes:
                    blocks.append("讲者备注：\n" + notes)
            text = "\n".join(blocks).strip()
            if text:
                pages.append(PageText(page=number, text=text))
    except Exception as exc:
        raise ParseError(f"PPTX 读取失败，文件可能损坏或已加密：{type(exc).__name__}") from exc
    if not pages:
        raise NoTextError("这份演示文稿没有可提取的文字，可能只有图片。本项目不含 OCR，请使用含可编辑文字的课件。")
    log.info("PPTX解析完成 %s：%d张幻灯片含文字", path.name, len(pages))
    return pages


def _parse_ppt(path: Path) -> list[PageText]:
    import subprocess
    import sys
    import tempfile

    with path.open("rb") as stream:
        if stream.read(8) != bytes.fromhex("D0CF11E0A1B11AE1"):
            raise ParseError("不是有效的旧版 PPT 文件。请在 PowerPoint 中另存为 PPTX 后上传，不要只修改扩展名。")
    if sys.platform != "win32":
        raise ParseError("旧版 PPT 需 Windows 和本机 PowerPoint；此环境请先将文件另存为 PPTX 后上传。")
    # Office调用可能等待弹窗，用独立进程限制等待时间，不能让上传界面无限卡住。
    with tempfile.TemporaryDirectory(prefix="coursemate_ppt_") as directory:
        target = Path(directory) / "converted.pptx"
        worker = Path(__file__).with_name("ppt_legacy_worker.py")
        try:
            result = subprocess.run(
                [sys.executable, str(worker), str(path.resolve()), str(target)],
                capture_output=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise ParseError("旧版 PPT 转换超时。请关闭可能出现的 PowerPoint 对话框，将文件另存为 PPTX 后重试。") from exc
        except OSError as exc:
            raise ParseError("无法启动旧版 PPT 转换，请将文件另存为 PPTX 后上传。") from exc
        if result.returncode != 0 or not target.exists():
            raise ParseError("旧版 PPT 转换失败。请确认本机已安装且可正常打开 PowerPoint，并安装 pywin32；也可先另存为 PPTX 后上传。")
        return _parse_pptx(target)


_PARSERS = {".pdf": _parse_pdf, ".docx": _parse_docx, ".txt": _parse_txt,
            ".pptx": _parse_pptx, ".ppt": _parse_ppt}


def parse_file(path: Path) -> list[PageText]:
    """按扩展名分发解析。未知类型直接拒绝。"""
    path = Path(path)
    if not path.exists():
        raise ParseError(f"文件不存在：{path.name}")
    ext = path.suffix.lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise ParseError(f"不支持的文件类型 {ext}，仅支持 PDF / DOCX / TXT / PPTX / PPT。")
    if path.stat().st_size == 0:
        raise ParseError("文件大小为 0。")
    return parser(path)
