"""`settings.data_sources.equity` 的解析与写侧校验。

配置是「换实现」的唯一入口：改 `provider` 就换实现、换落库周期；标的清单与调度周期
各自独立，改一个不覆盖另一个。非法值必须在写入时拒绝，不能等到读配置时才炸。
"""

from __future__ import annotations

import pytest

from app.core import ValidationError
from app.equity.config import (
    ALLOWED_INTERVALS,
    DEFAULT_SYMBOLS,
    clean_symbols,
    resolve_config,
    validate_equity_override,
)


def test_defaults_apply_when_the_group_is_missing() -> None:
    config = resolve_config({})

    assert config.provider == "yahoo"
    assert config.symbols == DEFAULT_SYMBOLS
    assert config.bar == "1m"
    assert config.interval == "1m"
    assert config.interval_seconds == ALLOWED_INTERVALS["1m"]
    assert config.url is not None


def test_switching_provider_switches_the_bar_but_not_the_symbols() -> None:
    config = resolve_config({"equity": {"provider": "stooq"}})

    assert config.provider == "stooq"
    assert config.bar == "1d"
    assert config.symbols == DEFAULT_SYMBOLS
    assert config.options()["url"] is not None


def test_symbols_are_cleaned_and_deduplicated() -> None:
    config = resolve_config({"equity": {"symbols": [" SPY ", "QQQ", "SPY", ""]}})

    assert config.symbols == ("SPY", "QQQ")


def test_scheduler_interval_is_validated() -> None:
    config = resolve_config({"equity": {"scheduler": {"minute": "5m"}}})
    assert config.interval_seconds == 300


def test_unknown_provider_is_rejected_at_read_time() -> None:
    with pytest.raises(ValidationError, match="polygon"):
        resolve_config({"equity": {"provider": "polygon"}})


def test_unknown_interval_is_rejected_at_read_time() -> None:
    with pytest.raises(ValidationError, match="1h"):
        resolve_config({"equity": {"scheduler": {"minute": "1h"}}})


def test_write_side_validation_rejects_an_unknown_provider() -> None:
    with pytest.raises(ValidationError, match=r"stooq|yahoo"):
        validate_equity_override(provider="polygon")


@pytest.mark.parametrize("symbols", [[], [""], ["SP Y"], ["X" * 17]])
def test_write_side_validation_rejects_bad_symbols(symbols: list[str]) -> None:
    with pytest.raises(ValidationError):
        validate_equity_override(symbols=symbols)


def test_write_side_validation_accepts_a_known_pair() -> None:
    validate_equity_override(provider="stooq", symbols=["SPY", "QQQ"])


def test_clean_symbols_tolerates_non_sequences() -> None:
    assert clean_symbols(None) == ()
    assert clean_symbols("SPY") == ()
    assert clean_symbols([1, "SPY", None]) == ("SPY",)
