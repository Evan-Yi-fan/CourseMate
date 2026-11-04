"""大模型调用封装。

统一走 OpenAI 兼容接口，供应商由配置决定（DeepSeek / 通义千问 / 其他），
业务代码里只认 LLMService，不认识具体厂商。

设计要点：
- 密钥只从 Settings 来，日志里只出现打码后的值；
- 超时、重试、错误分类集中在这里，上层拿到的永远是可读的中文错误；
- ping() 发起短请求验证连通性，不修改配置或学习数据。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from config.settings import Settings, mask_secret

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """模型调用失败的基类，消息可直接展示给用户。"""


class LLMNotConfigured(LLMError):
    """缺少 API Key / 模型名等必要配置。"""


class LLMTimeout(LLMError):
    pass


class LLMUpstreamError(LLMError):
    pass


@dataclass
class ChatResult:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: OpenAI | None = None

    # ------------------------------------------------------------------
    def _ensure_ready(self) -> None:
        if not self.settings.llm_ready:
            missing = "、".join(self.settings.llm_missing())
            raise LLMNotConfigured(
                f"大模型尚未配置，缺少：{missing}。"
                "请到「模型设置」填写 API 地址、密钥与可用模型名称，也可使用 .env 配置。"
            )

    @property
    def client(self) -> OpenAI:
        self._ensure_ready()
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url,
                timeout=self.settings.llm_timeout,
                max_retries=0,  # 重试由本类控制，便于记录日志与统计
            )
            log.info(
                "LLM 客户端已创建 provider=%s base_url=%s model=%s key=%s",
                self.settings.llm_provider,
                self.settings.llm_base_url,
                self.settings.llm_model,
                mask_secret(self.settings.llm_api_key),
            )
        return self._client

    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> ChatResult:
        """单轮/多轮对话。失败会抛 LLMError 子类，附带可读原因。"""
        self._ensure_ready()
        attempts = max(1, self.settings.llm_max_retries + 1)
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                kwargs: dict[str, Any] = {
                    "model": self.settings.llm_model,
                    "messages": messages,
                    "temperature": (
                        self.settings.llm_temperature if temperature is None else temperature
                    ),
                }
                if max_tokens:
                    kwargs["max_tokens"] = max_tokens
                if json_mode:
                    # 部分供应商（含 DeepSeek）支持该字段；不支持时上层仍有 JSON 校验兜底
                    kwargs["response_format"] = {"type": "json_object"}

                resp = self.client.chat.completions.create(**kwargs)
                latency = int((time.perf_counter() - started) * 1000)
                text = (resp.choices[0].message.content or "").strip()
                usage = getattr(resp, "usage", None)
                result = ChatResult(
                    text=text,
                    model=getattr(resp, "model", self.settings.llm_model),
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    latency_ms=latency,
                )
                log.info(
                    "LLM 调用成功 model=%s latency=%dms tokens=%d/%d",
                    result.model, latency, result.prompt_tokens, result.completion_tokens,
                )
                return result

            except APITimeoutError as exc:
                last_exc = exc
                log.warning("LLM 第 %d/%d 次调用超时（%.0fs）", attempt, attempts,
                            self.settings.llm_timeout)
            except APIConnectionError as exc:
                last_exc = exc
                log.warning("LLM 第 %d/%d 次调用网络失败: %s", attempt, attempts, type(exc).__name__)
            except APIStatusError as exc:
                last_exc = exc
                # 4xx 里除了 429 基本都是重试无意义的（鉴权错、模型名错）
                if exc.status_code < 500 and exc.status_code != 429:
                    raise LLMUpstreamError(self._describe_status(exc)) from exc
                log.warning("LLM 第 %d/%d 次调用返回 %s", attempt, attempts, exc.status_code)
            except Exception as exc:  # 兜底：绝不把原始堆栈抛给界面
                raise LLMUpstreamError(f"大模型调用出现意外错误：{type(exc).__name__}") from exc

        if isinstance(last_exc, APITimeoutError):
            raise LLMTimeout(
                f"大模型响应超时（{self.settings.llm_timeout:.0f} 秒，已重试 {attempts - 1} 次）。"
                "请检查网络，或调大 LLM_TIMEOUT。"
            )
        raise LLMUpstreamError(
            f"无法连接大模型服务（{self.settings.llm_base_url}）。"
            "请检查网络连通性，或确认 LLM_BASE_URL 是否正确。"
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _describe_status(exc: APIStatusError) -> str:
        code = exc.status_code
        if code == 401:
            return "API Key 无效或已过期（401）。请到「模型设置」检查 API 密钥。"
        if code == 403:
            return "当前 Key 没有调用该模型的权限（403）。请确认账号已开通该模型。"
        if code == 404:
            return "模型或接口路径不存在（404）。请确认 LLM_MODEL 名称与 LLM_BASE_URL 是否匹配。"
        if code == 429:
            return "调用频率或额度超限（429）。请稍后再试，或检查账户余额。"
        return f"大模型服务返回错误（HTTP {code}）。请稍后重试。"

    # ------------------------------------------------------------------
    def ping(self) -> dict[str, Any]:
        """连通性测试：发一条极短的请求，验证 Key / Base URL / 模型名三者匹配。

        返回结构化结果而不是抛异常，方便自检脚本与界面直接展示。
        """
        started = time.perf_counter()
        try:
            result = self.chat(
                [{"role": "user", "content": "只回复两个字：可用"}],
                temperature=0.0,
                max_tokens=16,
            )
            return {
                "ok": True,
                "message": "连接成功",
                "model": result.model,
                "reply": result.text[:50],
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        except LLMNotConfigured as exc:
            return {"ok": False, "kind": "not_configured", "message": str(exc)}
        except LLMError as exc:
            return {"ok": False, "kind": "error", "message": str(exc)}
