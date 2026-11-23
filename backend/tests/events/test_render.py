"""模板渲染：四行固定结构、缺值整行省略、超长只截明细。

渲染是全项目唯一的入口，三个通道拿到的都是同一段文字，所以这里的断言就是
「手机、页面、Webhook 正文」三处的共同契约。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.events import DeliveryDigest, DigestItem, render_message
from app.events.sinks.render import MESSAGE_LIMIT, message_width

MOMENT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _digest(*alerts: dict[str, Any], counts: tuple[int, ...] | None = None) -> DeliveryDigest:
    items = tuple(
        DigestItem(alert=alert, count=1 if counts is None else counts[index])
        for index, alert in enumerate(alerts)
    )
    return DeliveryDigest(items=items, occurred_at=MOMENT)


def _alert(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": "al_1",
        "type": "price",
        "severity": "warning",
        "title": "价格偏离参考价",
        "detail": "XAAPL-USDT 最新成交价 101.5 高于指数价 100",
        "instrument_id": "XAAPL-USDT",
    }
    values.update(overrides)
    return values


def test_single_alert_matches_the_documented_four_lines() -> None:
    """AC1：含 price/change_pct 的告警逐行匹配模板。"""

    digest = _digest(_alert(price="101.5", change_pct="+1.5%"))

    assert render_message(digest) == (
        "⚠️ 价格区间 · 警告\n"
        "XAAPL-USDT  101.5  +1.5%\n"
        "XAAPL-USDT 最新成交价 101.5 高于指数价 100\n"
        "2026-11-20T12:00:00Z"
    )


def test_missing_price_drops_the_whole_meta_line() -> None:
    """AC1：缺 price 时价格行整行消失，不留空行，也不留半截数字。"""

    digest = _digest(_alert(instrument_id="BTC-USDT-SWAP", change_pct="+1.5%"))

    assert render_message(digest) == (
        "⚠️ 价格区间 · 警告\nXAAPL-USDT 最新成交价 101.5 高于指数价 100\n2026-11-20T12:00:00Z"
    )


def test_missing_detail_drops_only_the_detail_line() -> None:
    digest = _digest(_alert(detail=""))

    assert render_message(digest).splitlines() == [
        "⚠️ 价格区间 · 警告",
        "2026-11-20T12:00:00Z",
    ]


def test_unknown_type_and_severity_fall_back_to_their_raw_names() -> None:
    """未登记的类型/级别原样显示：不伪造解释，也不隐藏这条通知。"""

    digest = _digest(_alert(type="bracket", severity="weird"))

    assert render_message(digest).splitlines()[0] == "🔔 bracket · weird"


def test_long_detail_is_truncated_but_instrument_and_time_survive() -> None:
    """AC1：超过上限时截断 detail 并追加 `…`，标的与时间保留。"""

    detail = "涨" * 5000
    digest = _digest(_alert(detail=detail, price="101.5", change_pct="+1.5%"))

    text = render_message(digest)

    assert message_width(text) <= MESSAGE_LIMIT
    lines = text.splitlines()
    assert lines[1] == "XAAPL-USDT  101.5  +1.5%"
    assert lines[2].endswith("…")
    assert lines[-1] == "2026-11-20T12:00:00Z"


def test_a_round_with_many_alerts_becomes_one_summary() -> None:
    """AC5：一轮 5 条 → 1 条摘要，首行有「本轮 5 条」与类型分布，明细最多 5 行。"""

    alerts = [
        _alert(id="al_1", type="risk", severity="critical", title="杠杆过高"),
        _alert(id="al_2", type="risk", severity="warning", title="止损距离过近"),
        _alert(id="al_3", type="risk", severity="warning", title="单标的占比过高"),
        _alert(id="al_4", type="indicator", severity="info", title="收盘价跌破 MA20"),
        _alert(id="al_5", type="indicator", severity="info", title="RSI 进入超卖观察区"),
    ]

    text = render_message(_digest(*alerts))
    lines = text.splitlines()

    assert lines[0] == "📊 本轮 5 条：持仓风险 3 · 技术形态 2"
    assert len(lines) == 1 + 5 + 1
    assert lines[1] == "- 🚨 杠杆过高  XAAPL-USDT"
    assert lines[-1] == "2026-11-20T12:00:00Z"


def test_summary_lists_at_most_five_details() -> None:
    alerts = [_alert(id=f"al_{index}", title=f"提醒 {index}") for index in range(7)]

    lines = render_message(_digest(*alerts)).splitlines()

    assert lines[0] == "📊 本轮 7 条：价格区间 7"
    assert len(lines) == 1 + 5 + 1


def test_merged_alerts_in_one_round_are_marked_with_a_count() -> None:
    """AC4：同一轮里同 (标的, 类型) 的 3 条合并成一条，正文带 `×3`。"""

    digest = _digest(_alert(type="indicator", severity="info"), counts=(3,))

    text = render_message(digest)

    assert text.splitlines() == [
        "📊 本轮 3 条：技术形态 3",
        "- 🔔 价格偏离参考价  XAAPL-USDT  ×3",
        "2026-11-20T12:00:00Z",
    ]
