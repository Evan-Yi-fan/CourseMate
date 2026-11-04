"""集中式配置。

原则：
1. 基础配置来自环境变量 / .env，模型配置可由本机界面保存的设置覆盖；
2. 缺配置时不是抛一个看不懂的堆栈，而是给出"缺哪一项、去哪配"的可读错误；
3. 路径一律解析成绝对路径，避免 Streamlit 在 pages/ 下标页时工作目录变化导致读不到文件。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 支持的文档类型（与 F02 一致）
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".pptx", ".ppt"}
MAX_UPLOAD_MB_DEFAULT = 50

_TRUE = {"1", "true", "yes", "on"}


class ConfigError(RuntimeError):
    """配置缺失或非法。消息面向使用者，可直接显示在界面上。"""


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"环境变量 {name} 必须是数字，当前为 {raw!r}") from exc


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"环境变量 {name} 必须是整数，当前为 {raw!r}") from exc


def _resolve(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


def mask_secret(secret: str, keep: int = 4) -> str:
    """日志/界面里展示密钥时使用，永不输出完整值。"""
    if not secret:
        return "(未配置)"
    if len(secret) <= keep * 2:
        return "*" * len(secret)
    return f"{secret[:keep]}{'*' * 8}{secret[-keep:]}"


@dataclass(frozen=True)
class Settings:
    # ---- LLM ----
    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout: float = 60.0
    llm_max_retries: int = 1
    llm_temperature: float = 0.2

    # ---- Embedding ----
    # local: sentence-transformers 本地模型；openai: OpenAI 兼容的 embeddings 接口；hash: 离线降级
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_dim: int = 512
    # 国内网络访问 huggingface.co 常超时，可指向镜像（如 https://hf-mirror.com）
    hf_endpoint: str = ""
    # 模型已缓存后置 True：只读本地缓存，不再联网校验，启动更快也更稳
    embedding_offline: bool = False

    # ---- 存储 ----
    db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "coursemate.db")
    chroma_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "chroma")
    upload_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "uploads")

    # ---- 上传与分块 ----
    max_upload_mb: int = MAX_UPLOAD_MB_DEFAULT
    chunk_size: int = 600
    chunk_overlap: int = 100
    retrieval_top_k: int = 4
    # 低于该相似度的片段视为没有依据，直接拒答，避免模型硬编（阈值由阶段 B 实测标定）
    qa_min_score: float = 0.35
    qa_top_k: int = 4

    # ---- 运行 ----
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        env_path = env_file or (PROJECT_ROOT / ".env")
        if env_path.exists():
            # override=False：真实环境变量优先于 .env，方便 CI 或临时覆盖
            load_dotenv(env_path, override=False)

        s = cls(
            llm_provider=_env("LLM_PROVIDER", "deepseek"),
            llm_api_key=_env("LLM_API_KEY"),
            llm_base_url=_env("LLM_BASE_URL", "https://api.deepseek.com"),
            llm_model=_env("LLM_MODEL"),
            llm_timeout=_env_float("LLM_TIMEOUT", 60.0),
            llm_max_retries=_env_int("LLM_MAX_RETRIES", 1),
            llm_temperature=_env_float("LLM_TEMPERATURE", 0.2),
            embedding_provider=_env("EMBEDDING_PROVIDER", "local"),
            embedding_model=_env("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
            embedding_api_key=_env("EMBEDDING_API_KEY"),
            embedding_base_url=_env("EMBEDDING_BASE_URL"),
            embedding_dim=_env_int("EMBEDDING_DIM", 512),
            hf_endpoint=_env("HF_ENDPOINT"),
            embedding_offline=_env("EMBEDDING_OFFLINE", "false").lower() in _TRUE,
            db_path=_resolve(_env("DB_PATH", "data/coursemate.db")),
            chroma_path=_resolve(_env("CHROMA_PATH", "data/chroma")),
            upload_dir=_resolve(_env("UPLOAD_DIR", "data/uploads")),
            max_upload_mb=_env_int("MAX_UPLOAD_MB", MAX_UPLOAD_MB_DEFAULT),
            chunk_size=_env_int("CHUNK_SIZE", 600),
            chunk_overlap=_env_int("CHUNK_OVERLAP", 100),
            retrieval_top_k=_env_int("RETRIEVAL_TOP_K", 4),
            qa_min_score=_env_float("QA_MIN_SCORE", 0.35),
            qa_top_k=_env_int("QA_TOP_K", 4),
            log_level=_env("LOG_LEVEL", "INFO").upper(),
        )
        s.validate()
        from config.model_settings import apply
        return apply(s)

    # ------------------------------------------------------------------
    def validate(self) -> None:
        """只校验"结构上一定需要"的东西；LLM 未配置不算致命错误，
        因为阶段 A 允许先跑通界面与数据库，再由用户去填 Key。"""
        if self.chunk_overlap >= self.chunk_size:
            raise ConfigError(
                f"CHUNK_OVERLAP({self.chunk_overlap}) 必须小于 CHUNK_SIZE({self.chunk_size})"
            )
        if self.embedding_provider not in {"local", "openai", "hash"}:
            raise ConfigError(
                f"EMBEDDING_PROVIDER 只能是 local/openai/hash，当前为 {self.embedding_provider!r}"
            )
        if self.max_upload_mb <= 0:
            raise ConfigError("MAX_UPLOAD_MB 必须为正数")

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_api_key and self.llm_model and self.llm_base_url)

    def llm_missing(self) -> list[str]:
        missing = []
        if not self.llm_api_key:
            missing.append("LLM_API_KEY")
        if not self.llm_base_url:
            missing.append("LLM_BASE_URL")
        if not self.llm_model:
            missing.append("LLM_MODEL")
        return missing

    def ensure_dirs(self) -> None:
        for p in (self.db_path.parent, self.chroma_path, self.upload_dir):
            p.mkdir(parents=True, exist_ok=True)

    def as_dict(self) -> dict[str, Any]:
        """可安全展示的配置快照（密钥已打码）。"""
        return {
            "LLM_PROVIDER": self.llm_provider,
            "LLM_BASE_URL": self.llm_base_url or "(未配置)",
            "LLM_MODEL": self.llm_model or "(未配置)",
            "LLM_API_KEY": mask_secret(self.llm_api_key),
            "EMBEDDING_PROVIDER": self.embedding_provider,
            "EMBEDDING_MODEL": self.embedding_model,
            "DB_PATH": str(self.db_path),
            "CHROMA_PATH": str(self.chroma_path),
            "UPLOAD_DIR": str(self.upload_dir),
            "CHUNK": f"{self.chunk_size}/{self.chunk_overlap}",
            "TOP_K": self.retrieval_top_k,
            "QA_MIN_SCORE": self.qa_min_score,
        }


_cached: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    global _cached
    if _cached is None or reload:
        _cached = Settings.load()
    return _cached
