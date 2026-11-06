"""标的分类：类别与交易所映射（AC2）。

未知符号一律 `unclassified` + exchange=None，绝不臆造交易所。
"""

import pytest

from app.market.core.classification import (
    ASSET_CLASSES,
    classify,
    participates_in_correlation,
)
from tests.market.support import load_fixture


@pytest.mark.parametrize(
    ("symbol", "asset_class", "exchange"),
    [
        ("AAPL", "us_equity", "XNAS"),
        ("SPY", "etf", "NYSE_ARCA"),
        ("QQQ", "etf", "NYSE_ARCA"),
        ("TSLL", "etf", "NYSE_ARCA"),
        ("US500", "index", None),
        ("JP225", "index", None),
        ("SONY", "foreign_equity", "XTKS"),
        ("OPENAI", "private_company", None),
        ("ANTHROPIC", "private_company", None),
    ],
)
def test_classification_table(symbol: str, asset_class: str, exchange: str | None) -> None:
    result = classify(symbol)
    assert result.asset_class == asset_class
    assert result.asset_class in ASSET_CLASSES
    assert result.exchange == exchange


def test_unknown_symbol_is_unclassified_not_guessed() -> None:
    result = classify("NOT-A-REAL-TICKER")
    assert result.asset_class == "unclassified"
    assert result.exchange is None


def test_only_us_equity_and_etf_participate_in_correlation() -> None:
    assert participates_in_correlation("us_equity") is True
    assert participates_in_correlation("etf") is True
    for other in ("index", "foreign_equity", "private_company", "unclassified"):
        assert participates_in_correlation(other) is False


def test_recorded_snapshot_classifies_shares_without_hardcoding_count() -> None:
    """股票类（instCategory=3）必须都有 asset_class；数量与上游一致，不写死 227。"""

    fixture = load_fixture("instruments_swap.json")
    stocks = [item for item in fixture["data"] if str(item.get("instCategory")) == "3"]
    assert stocks
    assert fixture["_meta"]["recorded_stock_count"] >= len(stocks)
    for item in stocks:
        assert classify(item["instId"].split("-", 1)[0]).asset_class in ASSET_CLASSES
