"""宏观配置解析：序列 → provider 的映射、上游地址来自配置、周期白名单。"""

from __future__ import annotations

import pytest

from app.core import ValidationError
from app.macro.config import resolve_config, validate_series_override
from app.macro.series import DEFAULT_PROVIDERS
from app.settings import DEFAULT_DATA_SOURCES


def _passwordless_defaults() -> dict[str, object]:
    return {"macro": {"series": {}, "scheduler": {"minute": "1m"}}}


def test_defaults_expand_to_all_units() -> None:
    config = resolve_config(_passwordless_defaults())

    assert config.interval == "1m"
    assert config.interval_seconds == 60
    assert [(unit.series_id, unit.granularity, unit.provider) for unit in config.units()] == [
        ("us10y", "minute", "yahoo"),
        ("us10y", "daily", "treasury"),
        ("us2y", "daily", "treasury"),
        ("vix", "minute", "yahoo"),
        ("vix", "daily", "cboe"),
    ]


def test_settings_defaults_match_macro_defaults() -> None:
    """两处各写了一份默认值；这条断言保证它们不会各说各话。"""

    assert DEFAULT_DATA_SOURCES["macro"]["series"] == DEFAULT_PROVIDERS


def test_switching_vix_minute_provider_keeps_other_series() -> None:
    config = resolve_config(
        {
            "macro": {
                "series": {"vix": {"minute": "cboe"}},
                "scheduler": {"minute": "1m"},
            }
        }
    )

    assert config.provider_for("vix", "minute") == "cboe"
    assert config.provider_for("vix", "daily") == "cboe"
    assert config.provider_for("us10y", "daily") == "treasury"


def test_unregistered_provider_is_a_config_error() -> None:
    with pytest.raises(ValidationError, match="未登记"):
        resolve_config({"macro": {"series": {"vix": {"minute": "alphavantage"}}}})


def test_unknown_interval_is_rejected() -> None:
    with pytest.raises(ValidationError, match="调度周期"):
        resolve_config({"macro": {"scheduler": {"minute": "1h"}}})


def test_five_minute_interval_is_allowed() -> None:
    config = resolve_config({"macro": {"scheduler": {"minute": "5m"}}})

    assert config.interval_seconds == 300


def test_series_override_accepts_registered_provider() -> None:
    validate_series_override({"vix": {"minute": "cboe"}})


def test_series_override_rejects_unknown_series() -> None:
    with pytest.raises(ValidationError, match="未登记的宏观序列"):
        validate_series_override({"us30y": {"daily": "treasury"}})


def test_series_override_rejects_provider_not_allowed_for_series() -> None:
    """已登记但不适用于该序列的 provider 也要拒绝，并列出该序列可选的值。"""

    with pytest.raises(ValidationError) as caught:
        validate_series_override({"vix": {"minute": "treasury"}})

    message = str(caught.value)
    assert "cboe" in message and "yahoo" in message


def test_series_override_rejects_unknown_granularity() -> None:
    with pytest.raises(ValidationError, match="没有"):
        validate_series_override({"us2y": {"minute": "treasury"}})


def test_daily_slot_rejects_a_minute_only_provider() -> None:
    """日结槽填分钟级源会让利差用「分钟级 10Y 减日线 2Y」，写入时就该拒绝。"""

    with pytest.raises(ValidationError) as caught:
        validate_series_override({"us10y": {"daily": "yahoo"}})

    assert "treasury" in str(caught.value)


def test_minute_slot_rejects_a_settlement_provider() -> None:
    """分钟槽填结算源会把日结值当成盘中读数，同样拒绝。"""

    with pytest.raises(ValidationError) as caught:
        validate_series_override({"us10y": {"minute": "treasury"}})

    assert "yahoo" in str(caught.value)


def test_config_rejects_daily_slot_with_minute_only_provider() -> None:
    with pytest.raises(ValidationError, match="不支持 provider"):
        resolve_config(
            {
                "macro": {
                    "series": {"us10y": {"daily": "yahoo"}},
                    "scheduler": {"minute": "1m"},
                }
            }
        )


def test_vix_minute_still_switches_between_cboe_and_yahoo() -> None:
    """AC1 要求设置页能在两个 provider 之间切换 vix.minute，两者都必须被接受。"""

    validate_series_override({"vix": {"minute": "cboe"}})
    validate_series_override({"vix": {"minute": "yahoo"}})
