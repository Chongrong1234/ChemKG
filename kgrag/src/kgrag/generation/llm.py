"""OpenAI 兼容 LLM 客户端.

特性：
- 非流式 ``chat()`` 与流式 ``chat_stream()`` 两种调用方式；
- 兼容 DeepSeek 系列等带 ``reasoning_content`` 的模型（思考过程单独回调）；
- 网络错误/超时不抛出到上层：调用方拿到 ``(None, error)`` 后走证据摘录兜底。
"""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass
from typing import Callable, Iterator

import httpx

from kgrag.config import Settings, get_settings

logger = logging.getLogger("kgrag.llm")

# 流式回调：("content", delta) | ("reasoning", delta)
StreamCallback = Callable[[str, str], None]


@dataclass
class LLMResult:
    """一次生成的结果."""

    content: str
    reasoning: str = ""
    error: str | None = None
    model: str = ""
    usage: dict | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.content)


class LLMClient:
    """OpenAI 兼容 Chat Completions 客户端."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @classmethod
    def with_overrides(cls, *, base_url: str | None = None, api_key: str | None = None,
                       model: str | None = None, settings: Settings | None = None) -> "LLMClient":
        """按用户级配置覆盖构造客户端副本（不污染全局 Settings 单例）.

        任意字段留空则沿用服务端默认。用于「用户自带接口」场景。
        """
        s = settings or get_settings()
        kwargs: dict = {}
        if base_url:
            kwargs["llm_base_url"] = base_url
        if api_key:
            kwargs["llm_api_key"] = api_key
        if model:
            kwargs["llm_model"] = model
        if kwargs:
            s = dataclasses.replace(s, **kwargs)
        return cls(s)

    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, messages: list[dict], *, stream: bool, thinking: bool | None = None,
                 max_tokens: int | None = None) -> dict:
        """构造请求体；thinking=False 时关闭 reasoning（更快出正文）."""
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": self.settings.llm_temperature,
            "max_tokens": max_tokens or self.settings.llm_max_tokens,
            "stream": stream,
        }
        if thinking is None:
            thinking = self.settings.llm_thinking
        if not thinking:
            # OpenAI 兼容网关通用的思考关闭参数；不支持的网关会忽略
            payload["reasoning_effort"] = "none"
            payload["enable_thinking"] = False
        return payload

    # ------------------------------------------------------------------
    def chat(self, messages: list[dict], *, thinking: bool | None = None,
             max_tokens: int | None = None) -> LLMResult:
        """非流式补全；失败时返回带 error 的结果（不抛异常）."""
        base = self.settings.llm_base_url.rstrip("/")
        if not self.settings.llm_enabled:
            return LLMResult(content="", error="LLM 未配置（缺 API key / base_url / model）")
        try:
            with httpx.Client(timeout=self.settings.llm_timeout_s) as client:
                resp = client.post(f"{base}/chat/completions", headers=self._headers(),
                                   json=self._payload(messages, stream=False, thinking=thinking,
                                                      max_tokens=max_tokens))
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001 - 统一降级为兜底回答
            logger.warning("LLM chat failed: %s", exc)
            return LLMResult(content="", error=f"{type(exc).__name__}: {exc}", model=self.settings.llm_model)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return LLMResult(
            content=message.get("content") or "",
            reasoning=message.get("reasoning_content") or "",
            model=data.get("model", self.settings.llm_model),
            usage=data.get("usage"),
        )

    # ------------------------------------------------------------------
    def chat_stream(self, messages: list[dict], on_delta: StreamCallback,
                    *, thinking: bool | None = None) -> LLMResult:
        """流式补全；on_delta 按序回调 ("reasoning", ...) 与 ("content", ...) 增量."""
        base = self.settings.llm_base_url.rstrip("/")
        if not self.settings.llm_enabled:
            return LLMResult(content="", error="LLM 未配置（缺 API key / base_url / model）")
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage: dict | None = None
        try:
            with httpx.Client(timeout=self.settings.llm_timeout_s) as client:
                with client.stream("POST", f"{base}/chat/completions", headers=self._headers(),
                                   json=self._payload(messages, stream=True, thinking=thinking)) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                        if delta.get("reasoning_content"):
                            piece = delta["reasoning_content"]
                            reasoning_parts.append(piece)
                            on_delta("reasoning", piece)
                        if delta.get("content"):
                            piece = delta["content"]
                            content_parts.append(piece)
                            on_delta("content", piece)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM stream failed: %s", exc)
            return LLMResult(content="", reasoning="".join(reasoning_parts),
                             error=f"{type(exc).__name__}: {exc}", model=self.settings.llm_model)
        return LLMResult(content="".join(content_parts), reasoning="".join(reasoning_parts),
                         model=self.settings.llm_model, usage=usage)
