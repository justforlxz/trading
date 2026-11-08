"""语言模型适配层: 外部调用只出现在这里, `api` 层不直接接触 httpx。

三种 provider:
- `none`     → 不具备回答能力 (调用方统一 503) ;
- `rule_based` → 不请求网络, 由 core 的确定性摘要回答, 响应显式 `degraded=true`;
- `openai`   → OpenAI 兼容的 `/chat/completions`, 失败时可按配置降级。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from app.ai.config import PROVIDER_NONE, PROVIDER_OPENAI, PROVIDER_RULE_BASED, AiConfig


class UpstreamFailure(Exception):
    """模型服务不可用或返回不可解析的结果。"""


@dataclass(frozen=True, slots=True)
class LlmResult:
    text: str
    provider: str
    model: str
    tokens: int | None = None


@runtime_checkable
class LlmAdapter(Protocol):
    """适配器只负责把提示词变成文本, 不做任何事实加工。"""

    provider: str
    model: str

    async def complete(self, *, system: str, prompt: str) -> LlmResult: ...


class RuleBasedAdapter:
    """规则式适配器: 原样返回确定性提示词, 不引入任何模型生成内容。"""

    provider = PROVIDER_RULE_BASED
    model = "rules-v1"

    async def complete(self, *, system: str, prompt: str) -> LlmResult:
        del system
        return LlmResult(text=prompt, provider=self.provider, model=self.model, tokens=None)


class OpenAiCompatibleAdapter:
    """OpenAI 兼容的 chat completions 客户端 (只读文本, 不调用工具) 。"""

    provider = PROVIDER_OPENAI

    def __init__(
        self,
        config: AiConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = config.model
        self._config = config
        self._client = client

    async def complete(self, *, system: str, prompt: str) -> LlmResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self._config.api_key}"}
        try:
            if self._client is not None:
                response = await self._client.post(self._endpoint(), json=payload, headers=headers)
            else:
                timeout = httpx.Timeout(self._config.timeout_seconds)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(self._endpoint(), json=payload, headers=headers)
        except httpx.HTTPError as exc:  # 连接失败、超时、DNS 等
            raise UpstreamFailure(f"model request failed: {exc}") from exc

        if response.status_code >= 400:
            raise UpstreamFailure(
                f"model returned HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise UpstreamFailure("model response is not a chat completion") from exc
        if not isinstance(text, str) or not text.strip():
            raise UpstreamFailure("model returned empty content")
        usage = body.get("usage") if isinstance(body, dict) else None
        tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        return LlmResult(
            text=text.strip(),
            provider=self.provider,
            model=self.model,
            tokens=tokens if isinstance(tokens, int) else None,
        )

    def _endpoint(self) -> str:
        return f"{self._config.base_url}/chat/completions"


def build_adapter(
    config: AiConfig, *, client: httpx.AsyncClient | None = None
) -> LlmAdapter | None:
    """按 provider 构造适配器; `none` 返回 `None`, 由调用方转成 503。"""

    if config.provider == PROVIDER_RULE_BASED:
        return RuleBasedAdapter()
    if config.provider == PROVIDER_OPENAI:
        return OpenAiCompatibleAdapter(config, client=client)
    if config.provider == PROVIDER_NONE:
        return None
    return None


__all__ = [
    "LlmAdapter",
    "LlmResult",
    "OpenAiCompatibleAdapter",
    "RuleBasedAdapter",
    "UpstreamFailure",
    "build_adapter",
]
