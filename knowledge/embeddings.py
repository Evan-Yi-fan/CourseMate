"""文本向量化。

三种后端，按需切换，接口一致：

| provider | 说明 | 适用 |
|---|---|---|
| local  | sentence-transformers + bge-small-zh-v1.5 | 默认。离线推理，中文效果好 |
| openai | OpenAI 兼容的 /embeddings 接口 | 本地跑不动模型时，换云端 |
| hash   | 字符 n-gram 哈希（确定性、零依赖） | 仅用于跑通链路与单元测试 |

模型加载是重量级操作（首次要下载 ~100MB），所以按 (provider, model) 缓存单例。
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
from typing import Protocol

from config.settings import Settings, mask_secret

log = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[tuple[str, str], "Embedder"] = {}


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    name: str
    dim: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbedder:
    """sentence-transformers 本地模型。"""

    def __init__(self, model_name: str, hf_endpoint: str = "", offline: bool = False):
        if hf_endpoint:
            # 必须在 import sentence_transformers 之前设置才会生效
            os.environ.setdefault("HF_ENDPOINT", hf_endpoint)
        if offline:
            # 只读本地缓存：模型已下载过时，避免每次启动都联网校验（网络抖动会拖慢首屏）
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingError(
                "未安装 sentence-transformers，无法使用本地向量模型。"
                "可执行 pip install sentence-transformers，"
                "或把 EMBEDDING_PROVIDER 改为 openai / hash。"
            ) from exc

        try:
            self._model = SentenceTransformer(model_name)
        except Exception as exc:
            raise EmbeddingError(
                f"本地向量模型 {model_name} 加载失败：{type(exc).__name__}。"
                "首次运行需要联网下载模型；国内网络可设置 HF_ENDPOINT=https://hf-mirror.com。"
            ) from exc

        self.name = f"local:{model_name}"
        # sentence-transformers 6.x 改了方法名，这里兼容新旧两版
        get_dim = getattr(self._model, "get_embedding_dimension", None) \
            or self._model.get_sentence_embedding_dimension
        self.dim = int(get_dim())
        log.info("本地向量模型就绪 %s (dim=%d)", model_name, self.dim)

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self._model.encode(
            texts, batch_size=16, normalize_embeddings=True,
            show_progress_bar=False, convert_to_numpy=True,
        )
        return [v.tolist() for v in vecs]


class OpenAIEmbedder:
    """OpenAI 兼容的 embeddings 接口（可指向任何兼容服务）。"""

    def __init__(self, model_name: str, api_key: str, base_url: str):
        if not api_key:
            raise EmbeddingError("EMBEDDING_PROVIDER=openai 时需要设置 EMBEDDING_API_KEY")
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=60)
        self._model_name = model_name
        self.name = f"openai:{model_name}"
        self.dim = 0  # 首次调用后确定
        log.info("云端向量模型就绪 %s key=%s", model_name, mask_secret(api_key))

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = self._client.embeddings.create(model=self._model_name, input=texts)
        except Exception as exc:
            raise EmbeddingError(f"云端向量接口调用失败：{type(exc).__name__}") from exc
        vecs = [d.embedding for d in resp.data]
        if not self.dim:
            self.dim = len(vecs[0])
        return vecs


class HashEmbedder:
    """确定性哈希向量：只为跑通链路，不具备真实语义能力。

    实现是字符 bigram 的 hashing trick + L2 归一化。
    它保证同一文本永远得到同一向量，因此可以用来测"写入/检索/持久化"是否正确。
    """

    def __init__(self, dim: int = 512):
        self.name = f"hash:{dim}"
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        t = text.strip()
        for i in range(len(t)):
            gram = t[max(0, i - 1):i + 2]
            h = int.from_bytes(hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(), "big")
            v[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v))
        return [x / norm for x in v] if norm else v

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


def get_embedder(settings: Settings) -> Embedder:
    """按配置返回（并缓存）向量化后端。"""
    key = (settings.embedding_provider, settings.embedding_model)
    with _lock:
        if key in _cache:
            return _cache[key]

        provider = settings.embedding_provider
        if provider == "local":
            emb: Embedder = LocalEmbedder(
                settings.embedding_model, settings.hf_endpoint, settings.embedding_offline
            )
        elif provider == "openai":
            emb = OpenAIEmbedder(
                settings.embedding_model, settings.embedding_api_key, settings.embedding_base_url
            )
        elif provider == "hash":
            emb = HashEmbedder(settings.embedding_dim)
            log.warning("正在使用 hash 向量后端：仅用于调试，检索质量不代表真实效果")
        else:  # Settings.validate 已经拦过一次
            raise EmbeddingError(f"未知的 EMBEDDING_PROVIDER: {provider}")

        _cache[key] = emb
        return emb


def reset_cache() -> None:
    """测试用：清掉已加载的模型。"""
    with _lock:
        _cache.clear()
