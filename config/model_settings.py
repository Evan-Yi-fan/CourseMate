"""界面模型配置：只覆盖模型字段，原子保存到本机数据目录。"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from config.settings import ConfigError, Settings

FIELDS = {"llm_provider", "llm_base_url", "llm_api_key", "llm_model", "llm_timeout"}
log = logging.getLogger(__name__)


def config_path(settings: Settings) -> Path:
    return settings.db_path.parent / "model_settings.json"


def candidate(settings: Settings, *, provider: str, base_url: str, api_key: str,
              model: str, timeout: float = 60) -> Settings:
    base_url, model, api_key = base_url.strip().rstrip('/'), model.strip(), api_key.strip()
    try:
        url = urlsplit(base_url)
        valid = url.scheme in {"http", "https"} and bool(url.hostname) and url.port != 0
    except ValueError:
        valid = False
    if not valid or any(ch.isspace() or ord(ch) < 32 for ch in base_url) or url.username or url.password or url.query or url.fragment:
        raise ConfigError("接口地址须为有效的 HTTP/HTTPS 根地址，不能包含密钥、账号、查询参数或片段。")
    if url.path.rstrip('/').endswith('/chat/completions'):
        raise ConfigError("请填写接口根地址，不要附加 /chat/completions。")
    if not model or len(model) > 200 or any(ord(ch) < 32 for ch in model):
        raise ConfigError("请填写供应商可用的模型名称。")
    if not api_key:
        # 更换地址后不把原供应商密钥默默发送到新地址。
        if base_url != settings.llm_base_url.rstrip('/') or not settings.llm_api_key:
            raise ConfigError("请填写 API 密钥；更换接口地址后需重新填写密钥。")
        api_key = settings.llm_api_key
    if not 5 <= float(timeout) <= 180:
        raise ConfigError("请求超时须在 5–180 秒之间。")
    return replace(settings, llm_provider=provider.strip() or "custom", llm_base_url=base_url,
                   llm_api_key=api_key, llm_model=model, llm_timeout=float(timeout))


def read(settings: Settings) -> dict:
    path = config_path(settings)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != FIELDS:
            raise ValueError("Invalid fields")
        validated = candidate(settings, provider=data["llm_provider"], base_url=data["llm_base_url"],
                              api_key=data["llm_api_key"], model=data["llm_model"], timeout=data["llm_timeout"])
        return {field: getattr(validated, field) for field in FIELDS}
    except Exception as exc:
        raise ConfigError("本地模型配置无法读取，请在「模型设置」中重新保存。") from exc


def apply(settings: Settings) -> Settings:
    if settings.public_demo:
        return settings
    try:
        return replace(settings, **read(settings))
    except ConfigError:
        log.warning("本地模型配置无效，暂时使用环境配置。")
        return settings


def save(settings: Settings) -> None:
    if settings.public_demo:
        raise ConfigError("公开体验版由管理员配置模型，访客不能修改。")
    validated = candidate(settings, provider=settings.llm_provider, base_url=settings.llm_base_url,
                          api_key=settings.llm_api_key, model=settings.llm_model, timeout=settings.llm_timeout)
    path = config_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        # mkstemp默认限制文件权限；同目录替换避免只写入半份配置。
        fd, name = tempfile.mkstemp(prefix=".model_", suffix=".tmp", dir=path.parent)
        temp = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({field: getattr(validated, field) for field in FIELDS}, handle, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    except OSError as exc:
        raise ConfigError("无法保存模型设置，请检查数据目录的写入权限；原配置未覆盖。") from exc
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
