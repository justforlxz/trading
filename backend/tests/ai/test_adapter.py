"""P4-01: 适配层配置开关、规则式路径与 OpenAI 兼容客户端（全部假响应）。"""

from __future__ import annotations

import httpx
import pytest

from app.ai.adapter import (
    OpenAiCompatibleAdapter,
    RuleBasedAdapter,
    UpstreamFailure,
    build_adapter,
)
from app.ai.config import (
    PROVIDER_NONE,
    PROVIDER_OPENAI,
    PROVIDER_RULE_BASED,
    RULE_MODEL,
    AiConfig,
    load_config,
)
from app.config import Settings


def _config(**overrides) -> AiConfig:
    base = {
        "ai_enabled": True,
        "ai_provider": PROVIDER_OPENAI,
        "ai_model": "test-model",
        "ai_base_url": "http://model.invalid/v1",
        "ai_api_key": "test-key",
    }
    base.update(overrides)
    return load_config(Settings(**base))


def test_default_settings_are_disabled() -> None:
    config = load_config(Settings())
    assert config.provider == PROVIDER_NONE
    assert config.available is False
    assert build_adapter(config) is None


def test_openai_requires_full_credentials() -> None:
    assert _config(ai_api_key="").available is False
    assert _config(ai_model="").available is False
    assert _config(ai_base_url="").available is False
    assert _config().available is True


def test_unknown_provider_falls_back_to_none() -> None:
    config = _config(ai_provider="anthropic")
    assert config.provider == PROVIDER_NONE
    assert config.available is False


def test_rule_based_is_available_without_credentials() -> None:
    config = _config(ai_provider=PROVIDER_RULE_BASED, ai_model="", ai_base_url="", ai_api_key="")
    assert config.available is True
    assert config.model_view() == {"provider": PROVIDER_RULE_BASED, "model": RULE_MODEL}
    adapter = build_adapter(config)
    assert isinstance(adapter, RuleBasedAdapter)


@pytest.mark.asyncio
async def test_rule_based_adapter_returns_prompt_without_network() -> None:
    adapter = RuleBasedAdapter()
    result = await adapter.complete(system="system", prompt="事实清单")
    assert result.text == "事实清单"
    assert result.provider == PROVIDER_RULE_BASED
    assert result.model == RULE_MODEL
    assert result.tokens is None


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_openai_adapter_posts_chat_completion_and_parses_usage() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "  模型回答  "}}],
                "usage": {"total_tokens": 17},
            },
        )

    client = _mock_client(handler)
    async with client:
        adapter = OpenAiCompatibleAdapter(_config(), client=client)
        result = await adapter.complete(system="只读", prompt="事实")

    assert seen["url"] == "http://model.invalid/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert '"stream":false' in str(seen["body"])
    assert result.text == "模型回答"
    assert result.tokens == 17
    assert result.provider == PROVIDER_OPENAI


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]}),
    ],
)
async def test_openai_adapter_maps_bad_responses_to_upstream_failure(response) -> None:
    client = _mock_client(lambda request: response)
    async with client:
        adapter = OpenAiCompatibleAdapter(_config(), client=client)
        with pytest.raises(UpstreamFailure):
            await adapter.complete(system="s", prompt="p")


@pytest.mark.asyncio
async def test_openai_adapter_maps_timeout_to_upstream_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("dead port", request=request)

    client = _mock_client(handler)
    async with client:
        adapter = OpenAiCompatibleAdapter(_config(), client=client)
        with pytest.raises(UpstreamFailure):
            await adapter.complete(system="s", prompt="p")
