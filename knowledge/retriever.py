"""ChromaDB 检索层。

一个持久化实例，按课程一个 collection（course_1、course_2 …），
每条向量都带完整 metadata，检索结果能直接还原成"文件名 + 页码 + 片段"。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from config.settings import Settings
from knowledge.embeddings import Embedder
from knowledge.splitter import Chunk

log = logging.getLogger(__name__)

_client_lock = threading.Lock()
_clients: dict[str, Any] = {}


class RetrievalError(RuntimeError):
    pass


@dataclass
class Hit:
    text: str
    filename: str
    page: int | None
    score: float            # 越大越相关（余弦相似度，范围约 0~1）
    document_id: int
    chunk_index: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text, "filename": self.filename, "page": self.page,
            "score": round(self.score, 4), "document_id": self.document_id,
            "chunk_index": self.chunk_index,
        }


def get_client(chroma_path: str):
    """同一路径复用同一个 client，避免重复打开底层文件句柄。"""
    with _client_lock:
        if chroma_path not in _clients:
            import chromadb

            _clients[chroma_path] = chromadb.PersistentClient(path=chroma_path)
            log.info("ChromaDB 客户端就绪: %s", chroma_path)
        return _clients[chroma_path]


def reset_clients() -> None:
    """测试用：丢掉已缓存的 client，释放底层文件句柄。"""
    with _client_lock:
        _clients.clear()


def collection_name(course_id: int) -> str:
    # Chroma 的 collection 名只允许字母数字和 _-，长度 3~63
    return f"course_{int(course_id)}"


class CourseIndex:
    def __init__(self, settings: Settings, course_id: int):
        self.settings = settings
        self.course_id = int(course_id)

    # ------------------------------------------------------------------
    def _collection(self):
        client = get_client(str(self.settings.chroma_path))
        name = collection_name(self.course_id)
        try:
            return client.get_or_create_collection(
                name=name, metadata={"hnsw:space": "cosine"}
            )
        except Exception:
            # 某些版本不接受该 metadata 写法，退回默认度量
            return client.get_or_create_collection(name=name)

    def count(self) -> int:
        try:
            return int(self._collection().count())
        except Exception as exc:
            log.warning("读取 collection 数量失败: %s", exc)
            return 0

    # ------------------------------------------------------------------
    def add_chunks(self, chunks: list[Chunk], *, document_id: int, filename: str,
                   embedder: Embedder) -> int:
        """写入一块文档的向量。写入前会先清掉该文档的旧向量，保证重复上传不产生重复 chunk。"""
        if not chunks:
            return 0
        self.delete_document(document_id)

        texts = [c.text for c in chunks]
        try:
            vectors = embedder.encode(texts)
        except Exception as exc:
            raise RetrievalError(f"向量化失败：{type(exc).__name__}: {exc}") from exc
        if len(vectors) != len(texts):
            raise RetrievalError("向量数量与文本数量不一致，已中止写入")

        ids = [f"c{self.course_id}_d{document_id}_k{c.chunk_index:04d}" for c in chunks]
        metadatas = [{
            "course_id": self.course_id,
            "document_id": int(document_id),
            "filename": filename,
            "page": -1 if c.page is None else int(c.page),   # Chroma 不接受 None
            "chunk_index": int(c.chunk_index),
        } for c in chunks]

        try:
            self._collection().add(ids=ids, documents=texts,
                                   embeddings=vectors, metadatas=metadatas)
        except Exception as exc:
            raise RetrievalError(f"写入向量库失败：{type(exc).__name__}: {exc}") from exc
        log.info("已写入 %d 个 chunk（课程 %d / 文档 %d）", len(ids), self.course_id, document_id)
        return len(ids)

    def delete_document(self, document_id: int, *, strict: bool = False) -> None:
        try:
            collection = self._existing_collection() if strict else self._collection()
            if collection is not None:
                collection.delete(where={"document_id": int(document_id)})
        except Exception as exc:
            if strict:
                raise RetrievalError("资料索引删除失败，请重试。") from exc
            # 首次入库时允许不存在旧索引；用户删除时必须报告真实失败。
            log.debug("清理旧向量时跳过: %s", exc)

    # ------------------------------------------------------------------
    def search(self, query: str, embedder: Embedder, top_k: int | None = None) -> list[Hit]:
        query = (query or "").strip()
        if not query:
            return []
        k = top_k or self.settings.retrieval_top_k
        try:
            vector = embedder.encode([query])[0]
        except Exception as exc:
            raise RetrievalError(f"问题向量化失败：{type(exc).__name__}") from exc

        try:
            res = self._collection().query(
                query_embeddings=[vector], n_results=k,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise RetrievalError(f"检索失败：{type(exc).__name__}") from exc

        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]

        hits: list[Hit] = []
        for text, meta, dist in zip(docs, metas, dists):
            meta = meta or {}
            page = meta.get("page")
            hits.append(Hit(
                text=text or "",
                filename=str(meta.get("filename", "")),
                page=None if page in (None, -1) else int(page),
                score=round(1.0 - float(dist), 4),   # cosine 距离 → 相似度
                document_id=int(meta.get("document_id", -1)),
                chunk_index=int(meta.get("chunk_index", -1)),
            ))
        return hits

    def sample(self, n: int = 6) -> list[Hit]:
        """取若干片段用于"没有指定知识点"时的出题上下文。

        用 get() 直接读，不走向量检索：出题需要覆盖全课程，
        而不是围绕某个具体问题召回。
        """
        try:
            data = self._collection().get(limit=max(1, n), include=["documents", "metadatas"])
        except Exception as exc:
            raise RetrievalError(f"读取课程片段失败：{type(exc).__name__}") from exc
        hits: list[Hit] = []
        for text, meta in zip(data.get("documents") or [], data.get("metadatas") or []):
            meta = meta or {}
            page = meta.get("page")
            hits.append(Hit(
                text=text or "",
                filename=str(meta.get("filename", "")),
                page=None if page in (None, -1) else int(page),
                score=1.0,
                document_id=int(meta.get("document_id", -1)),
                chunk_index=int(meta.get("chunk_index", -1)),
            ))
        return hits

    def sample_documents(self, document_ids: list[int], n: int = 6) -> list[Hit]:
        """逐份资料取样，确保所选资料有覆盖且不会混入未选文件。"""
        if not document_ids:
            return []
        per_document = max(1, (n + len(document_ids) - 1) // len(document_ids))
        hits = []
        try:
            collection = self._collection()
            for did in document_ids:
                data = collection.get(where={"document_id": int(did)}, limit=per_document,
                                      include=["documents", "metadatas"])
                if not data["ids"]:
                    raise RetrievalError("所选资料索引缺失，请先重建索引。")
                for text, meta in zip(data["documents"], data["metadatas"]):
                    page = meta.get("page")
                    hits.append(Hit(text=text or "", filename=meta.get("filename", ""),
                                    page=None if page in (None, -1) else int(page), score=1.0,
                                    document_id=int(meta["document_id"]), chunk_index=int(meta.get("chunk_index", -1))))
        except RetrievalError:
            raise
        except Exception as exc:
            raise RetrievalError("读取所选课程资料失败。") from exc
        return hits

    def _existing_collection(self):
        from chromadb.errors import NotFoundError
        try:
            return get_client(str(self.settings.chroma_path)).get_collection(collection_name(self.course_id))
        except NotFoundError:
            return None

    def backup(self, document_id: int | None = None) -> dict | None:
        """跨SQLite/文件/向量库删除前，保存必要数据以便失败时恢复。"""
        collection = self._existing_collection()
        if collection is None:
            return None
        query = {"where": {"document_id": int(document_id)}} if document_id is not None else {}
        return {"metadata": collection.metadata,
                "data": collection.get(include=["documents", "metadatas", "embeddings"], **query)}

    def restore(self, backup: dict | None) -> None:
        if backup is None:
            return
        kwargs = {"metadata": backup["metadata"]} if backup["metadata"] is not None else {}
        collection = get_client(str(self.settings.chroma_path)).get_or_create_collection(
            name=collection_name(self.course_id), **kwargs)
        data = backup["data"]
        if data["ids"]:
            collection.upsert(ids=data["ids"], documents=data["documents"],
                              metadatas=data["metadatas"], embeddings=data["embeddings"])

    def drop(self, *, strict: bool = False) -> None:
        try:
            if self._existing_collection() is not None:
                get_client(str(self.settings.chroma_path)).delete_collection(collection_name(self.course_id))
        except Exception as exc:
            if strict:
                raise RetrievalError("课程索引删除失败，请重试。") from exc
            log.warning("删除 collection 失败: %s", exc)
