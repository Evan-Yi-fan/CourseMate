"""文档服务：校验 → 落盘 → 解析 → 分块 → 向量化 → 写 Chroma → 更新状态。

一条原则：**SQLite 的文档状态必须和 ChromaDB 里的向量一致**。
所以每次入库都先删该文档的旧向量再重建，失败时把文档状态标成 failed 并记录原因，
绝不留一个"看着成功、其实检不到"的假状态。
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from config.settings import SUPPORTED_EXTENSIONS, Settings
from database import db
from knowledge.embeddings import EmbeddingError, get_embedder
from knowledge.parser import NoTextError, ParseError, parse_file
from knowledge.retriever import CourseIndex, RetrievalError
from knowledge.splitter import split_pages

log = logging.getLogger(__name__)


class UploadError(RuntimeError):
    """上传校验失败，消息直接展示给用户。"""


_UNSAFE = re.compile(r"[^\w\u4e00-\u9fff.\-]+")


def safe_filename(original: str) -> str:
    """去掉路径成分与危险字符，防止路径穿越（任务书 §11）。"""
    name = Path(original).name                  # 丢掉任何 ../ 前缀
    name = _UNSAFE.sub("_", name).strip("._") or "upload"
    return name[:120]


def validate_upload(settings: Settings, filename: str, size_bytes: int) -> str:
    """返回合法的扩展名；不合法则抛 UploadError。"""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        supported = " / ".join(sorted(e.lstrip(".").upper() for e in SUPPORTED_EXTENSIONS))
        raise UploadError(f"不支持的文件类型 {ext or '(无扩展名)'}，仅支持 {supported}。")
    if size_bytes <= 0:
        raise UploadError("文件是空的。")
    limit = settings.max_upload_mb * 1024 * 1024
    if size_bytes > limit:
        raise UploadError(
            f"文件超过 {settings.max_upload_mb}MB 限制（当前 {size_bytes / 1024 / 1024:.1f}MB）。"
        )
    return ext


def store_upload(settings: Settings, course_id: int, filename: str, data: bytes) -> Path:
    """按 课程目录/随机前缀_文件名 保存，避免同名覆盖。"""
    course_dir = Path(settings.upload_dir) / f"course_{course_id}"
    course_dir.mkdir(parents=True, exist_ok=True)
    safe = safe_filename(filename)
    target = course_dir / f"{uuid.uuid4().hex[:8]}_{safe}"
    target.write_bytes(data)
    log.info("已保存上传文件: %s (%d bytes)", target.name, len(data))
    return target


def ingest_document(settings: Settings, document_id: int, course_id: int,
                    file_path: Path, filename: str) -> dict[str, Any]:
    """执行解析与建索引。返回 {chunks, pages}；失败时抛出异常并已更新 DB 状态。"""
    db.set_document_status(settings.db_path, document_id, "pending")
    try:
        pages = parse_file(Path(file_path))
        chunks = split_pages(pages, settings.chunk_size, settings.chunk_overlap)
        embedder = get_embedder(settings)
        index = CourseIndex(settings, course_id)
        written = index.add_chunks(
            chunks, document_id=document_id, filename=filename, embedder=embedder
        )
        db.set_document_status(settings.db_path, document_id, "ready", chunk_count=written)
        log.info("文档 %d 入库完成：%d 页 / %d 块", document_id, len(pages), written)
        return {"chunks": written, "pages": len(pages)}
    except (ParseError, EmbeddingError, RetrievalError, ValueError) as exc:
        db.set_document_status(settings.db_path, document_id, "failed", 0, str(exc))
        log.warning("文档 %d 入库失败: %s", document_id, exc)
        raise
    except Exception as exc:  # 兜底，避免留下 pending 僵尸状态
        msg = f"{type(exc).__name__}: {exc}"
        db.set_document_status(settings.db_path, document_id, "failed", 0, msg)
        log.exception("文档 %d 入库出现意外错误", document_id)
        raise UploadError(f"处理失败：{msg}") from exc


def handle_upload(settings: Settings, course_id: int, filename: str,
                  data: bytes) -> dict[str, Any]:
    """上传→落盘→建库的完整流程，供界面调用。

    同名文档视为"同一份资料的更新"：复用原文档记录并覆盖向量，
    而不是新增一条记录再产生一份重复向量（任务书 §5.3）。
    """
    validate_upload(settings, filename, len(data))
    safe = safe_filename(filename)
    ext = Path(filename).suffix.lower().lstrip(".")

    existing = db.find_document_by_name(settings.db_path, course_id, safe)
    path = store_upload(settings, course_id, filename, data)

    if existing:
        doc_id = int(existing["id"])
        db.update_document_file(settings.db_path, doc_id, safe, str(path), ext)
        log.info("同名文档已存在（#%d），按更新处理：%s", doc_id, safe)
        result = ingest_document(settings, doc_id, course_id, path, safe)
        return {"document_id": doc_id, "replaced": True, **result}

    doc_id = db.create_document(settings.db_path, course_id, safe, str(path), ext)
    result = ingest_document(settings, doc_id, course_id, path, safe)
    return {"document_id": doc_id, "replaced": False, **result}


def reindex_document(settings: Settings, document_id: int) -> dict[str, Any]:
    """重建单个文档的索引（向量库被清掉或想换模型时用）。"""
    doc = db.get_document(settings.db_path, document_id)
    if not doc:
        raise UploadError(f"文档 {document_id} 不存在")
    return ingest_document(
        settings, document_id, int(doc["course_id"]), Path(doc["file_path"]), doc["filename"]
    )


def describe_documents(settings: Settings, course_id: int) -> list[dict[str, Any]]:
    docs = db.list_documents(settings.db_path, course_id)
    label = {"pending": "处理中", "ready": "已入库", "failed": "失败"}
    for d in docs:
        d["status_label"] = label.get(d["status"], d["status"])
    return docs


__all__ = [
    "UploadError", "safe_filename", "validate_upload", "store_upload",
    "ingest_document", "handle_upload", "reindex_document", "describe_documents",
    "NoTextError",
]
