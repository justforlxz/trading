"""风控通知设置：五条规则的开关、阈值与渠道。

两条必须成立的语义：

1. 关掉的规则**不再评估**（不只是不发通知）——否则页面上的命中条会与通知内容对不上；
2. 阈值只有一份：弹窗改的就是敞口判定读的那几个键，改完立刻生效。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core import ValidationError
from app.risk import (
    RULE_HIGH_LEVERAGE,
    RULE_STOP_DISTANCE,
    RULE_STOP_MISSING,
    RiskThresholds,
    build_exposure,
    load_notify_config,
    save_notify_config,
)
from app.risk.exposure import PositionRiskInput

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
ONE = Decimal("1")


def _thresholds(**overrides: Decimal) -> RiskThresholds:
    base = {
        "max_leverage": Decimal("3"),
        "max_single_instrument_weight_pct": Decimal("100"),
        "max_margin_usage_pct": Decimal("100"),
        "stop_distance_atr_multiple": ONE,
    }
    base.update(overrides)
    return RiskThresholds(**base)  # type: ignore[arg-type]


def _leveraged_position(lever: str = "8") -> PositionRiskInput:
    return PositionRiskInput(
        position_ref="exchange:okx-main:pos-1",
        source="exchange",
        inst_id="AAPL-USDT-SWAP",
        display_symbol="AAPL-USDT",
        side="long",
        size=Decimal("1"),
        inst_type="SWAP",
        mark_px=Decimal("100"),
        stop_px=Decimal("90"),
        atr=Decimal("5"),
        lever=Decimal(lever),
        sector=None,
        ct_val=Decimal("1"),
        ct_mult=Decimal("1"),
    )


def _evaluate(*, disabled: frozenset[str], thresholds: RiskThresholds | None = None):
    return build_exposure(
        (_leveraged_position(),),
        as_of=NOW,
        currency="USDT",
        thresholds=thresholds or _thresholds(),
        disabled_rules=disabled,
    )


def test_disabled_rule_is_not_evaluated_at_all() -> None:
    """关掉杠杆提醒后，杠杆再高也不产生命中行，也不打持仓标记。"""

    view = _evaluate(disabled=frozenset({RULE_HIGH_LEVERAGE}))

    assert [rule.rule_id for rule in view.rules] == []
    assert RULE_HIGH_LEVERAGE not in view.positions[0].flags


def test_enabled_rule_still_reports_the_violation() -> None:
    view = _evaluate(disabled=frozenset())

    assert [rule.rule_id for rule in view.rules] == [RULE_HIGH_LEVERAGE]
    assert RULE_HIGH_LEVERAGE in view.positions[0].flags


def test_stop_distance_threshold_controls_the_rule() -> None:
    """标记价到止损价是 2 倍 ATR：阈值 3 命中，阈值 1 不命中。"""

    loose = _evaluate(disabled=frozenset(), thresholds=_thresholds(max_leverage=Decimal("100")))
    tight = _evaluate(
        disabled=frozenset(),
        thresholds=_thresholds(
            max_leverage=Decimal("100"),
            stop_distance_atr_multiple=Decimal("3"),
        ),
    )

    assert RULE_STOP_DISTANCE not in [rule.rule_id for rule in loose.rules]
    assert RULE_STOP_DISTANCE in [rule.rule_id for rule in tight.rules]


# ------------------------------------------------------------------ 配置读写


def test_defaults_are_five_rules_with_margin_usage_off(client: TestClient) -> None:
    config = load_notify_config()

    assert [rule.rule_id for rule in config.rules] == [
        "stop_missing",
        "stop_distance",
        "high_leverage",
        "single_instrument_weight",
        "margin_usage",
    ]
    assert config.disabled() == frozenset({"margin_usage"})
    assert all(rule.channels for rule in config.rules)


def test_saved_switch_and_channels_survive_a_reread(client: TestClient) -> None:
    saved = save_notify_config(
        [
            {
                "rule_id": "high_leverage",
                "enabled": False,
                "channels": ["browser", "telegram"],
            }
        ]
    )

    again = load_notify_config()

    assert saved == again
    leverage = next(rule for rule in again.rules if rule.rule_id == "high_leverage")
    assert leverage.enabled is False
    assert leverage.channels == ("browser", "telegram")
    assert "high_leverage" in again.disabled()


def test_saved_threshold_is_the_one_exposure_reads(client: TestClient) -> None:
    """阈值只有一份：写进去的倍数就是敞口判定用的倍数。"""

    save_notify_config([{"rule_id": "stop_distance", "threshold": "2.5"}])

    config = load_notify_config()
    distance = next(rule for rule in config.rules if rule.rule_id == "stop_distance")

    assert distance.threshold == Decimal("2.5")


def test_unknown_rule_is_rejected(client: TestClient) -> None:
    with pytest.raises(ValidationError):
        save_notify_config([{"rule_id": "not_a_rule", "enabled": False}])


def test_enabled_rule_needs_at_least_one_channel(client: TestClient) -> None:
    with pytest.raises(ValidationError):
        save_notify_config([{"rule_id": "stop_missing", "enabled": True, "channels": []}])


def test_non_positive_threshold_is_rejected(client: TestClient) -> None:
    with pytest.raises(ValidationError):
        save_notify_config([{"rule_id": "high_leverage", "threshold": "0"}])


def test_api_can_read_and_write_the_config(client: TestClient) -> None:
    before = client.get("/api/risk/notify-config")
    assert before.status_code == 200, before.text
    assert len(before.json()["rules"]) == 5

    saved = client.put(
        "/api/risk/notify-config",
        json={"rules": [{"rule_id": "stop_missing", "enabled": False}]},
    )

    assert saved.status_code == 200, saved.text
    rules = {rule["rule_id"]: rule for rule in saved.json()["rules"]}
    assert rules["stop_missing"]["enabled"] is False
    # 未提交的规则保持原值
    assert rules["high_leverage"]["enabled"] is True


def test_api_rejects_an_unknown_rule(client: TestClient) -> None:
    response = client.put(
        "/api/risk/notify-config",
        json={"rules": [{"rule_id": "nope", "enabled": True}]},
    )

    assert response.status_code == 400, response.text


def test_saving_the_config_does_not_change_the_positions_page_numbers(
    client: TestClient,
) -> None:
    """保存只影响通知：权益、名义、保证金占用都不动。"""

    client.post("/api/account/sync")
    before = client.get("/api/account/summary").json()

    assert (
        client.put(
            "/api/risk/notify-config",
            json={"rules": [{"rule_id": "margin_usage", "enabled": True, "threshold": "1"}]},
        ).status_code
        == 200
    )

    after = client.get("/api/account/summary").json()

    for field in ("equity", "gross_notional", "net_notional", "margin_used", "margin_usage_pct"):
        assert after[field] == before[field]


# ------------------------------------------------------- 止损三态与命中统计


def _stop_status_position(stop_status: str | None, stop_px: Decimal | None) -> PositionRiskInput:
    return PositionRiskInput(
        position_ref="exchange:okx-main:pos-1",
        source="exchange",
        inst_id="AAPL-USDT-SWAP",
        display_symbol="AAPL-USDT",
        side="long",
        size=Decimal("1"),
        inst_type="SWAP",
        mark_px=Decimal("100"),
        stop_px=stop_px,
        atr=Decimal("5"),
        lever=Decimal("3"),
        sector=None,
        ct_val=Decimal("1"),
        ct_mult=Decimal("1"),
        stop_status=stop_status,
    )


def _exposure_for(position: PositionRiskInput):
    return build_exposure(
        (position,),
        as_of=NOW,
        currency="USDT",
        thresholds=_thresholds(max_leverage=Decimal("100")),
    )


def test_unavailable_stop_is_not_counted_as_missing() -> None:
    """「没查到止损」不能算成「没挂止损」——这正是本单要消灭的那句话。"""

    view = _exposure_for(_stop_status_position("unavailable", None))

    assert [rule.rule_id for rule in view.rules] == []
    assert view.positions[0].stop_status == "unavailable"
    assert RULE_STOP_MISSING not in view.positions[0].flags


def test_confirmed_absence_of_stop_is_counted() -> None:
    view = _exposure_for(_stop_status_position("none", None))

    assert [rule.rule_id for rule in view.rules] == [RULE_STOP_MISSING]
    assert view.positions[0].stop_status == "none"


def test_present_stop_is_not_counted_as_missing() -> None:
    view = _exposure_for(_stop_status_position("confirmed", Decimal("90")))

    assert RULE_STOP_MISSING not in [rule.rule_id for rule in view.rules]
    assert view.positions[0].stop_status == "confirmed"


def test_manual_position_without_status_keeps_the_two_state_behaviour() -> None:
    """手动持仓没有「没查到」这一说：用户填了就是有，没填就是没有。"""

    position = PositionRiskInput(
        position_ref="manual:abc",
        source="manual",
        inst_id="AAPL-USDT-SWAP",
        display_symbol="AAPL-USDT",
        side="long",
        size=Decimal("1"),
        inst_type="SWAP",
        mark_px=Decimal("100"),
        stop_px=None,
        atr=Decimal("5"),
        lever=Decimal("2"),
        sector=None,
        ct_val=Decimal("1"),
        ct_mult=Decimal("1"),
        stop_status=None,
    )

    assert [rule.rule_id for rule in _exposure_for(position).rules] == [RULE_STOP_MISSING]
