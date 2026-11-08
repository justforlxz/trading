"""助手配置: 外部模型默认关闭, provider 决定使用哪条适配路径。"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings

PROVIDER_NONE = "none"
PROVIDER_RULE_BASED = "rule_based"
PROVIDER_OPENAI = "openai"

RULE_MODEL = "rules-v1"
SUPPORTED_PROVIDERS = (PROVIDER_NONE, PROVIDER_RULE_BASED, PROVIDER_OPENAI)


@dataclass(frozen=True, slots=True)
class AiConfig:
    """一次请求使用的助手配置快照。"""

    enabled: bool
    provider: str
    model: str
    base_url: str
    api_key: str
    timeout_seconds: float
    max_tokens: int
    temperature: float
    fallback_enabled: bool
    max_citations: int

    @property
    def available(self) -> bool:
        """是否具备回答能力: 显式开启, 且模型/密钥按 provider 配齐。"""

        if not self.enabled or self.provider == PROVIDER_NONE:
            return False
        if self.provider == PROVIDER_RULE_BASED:
            return True
        if self.provider != PROVIDER_OPENAI:
            return False
        return bool(self.model and self.base_url and self.api_key)

    @property
    def rule_based(self) -> bool:
        return self.provider == PROVIDER_RULE_BASED

    def model_view(self) -> dict[str, str]:
        if self.rule_based:
            return {"provider": PROVIDER_RULE_BASED, "model": RULE_MODEL}
        return {"provider": self.provider, "model": self.model}


def load_config(settings: Settings) -> AiConfig:
    """把进程配置折叠成助手配置; 不认识的值一律视为不可用。"""

    provider = (settings.ai_provider or PROVIDER_NONE).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        provider = PROVIDER_NONE
    return AiConfig(
        enabled=settings.ai_enabled,
        provider=provider,
        model=settings.ai_model.strip(),
        base_url=settings.ai_base_url.strip().rstrip("/"),
        api_key=settings.ai_api_key.strip(),
        timeout_seconds=settings.ai_timeout_seconds,
        max_tokens=settings.ai_max_tokens,
        temperature=settings.ai_temperature,
        fallback_enabled=settings.ai_fallback_enabled,
        max_citations=settings.ai_max_citations,
    )


__all__ = [
    "PROVIDER_NONE",
    "PROVIDER_OPENAI",
    "PROVIDER_RULE_BASED",
    "RULE_MODEL",
    "SUPPORTED_PROVIDERS",
    "AiConfig",
    "load_config",
]
