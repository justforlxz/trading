"""回测预期的取数口径：只认当前标的集合与当前版本，且取最新一次运行。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.backtest import BacktestRunRow
from app.db import session_scope
from app.journal import latest_expectations
from app.strategy import InstanceRecord

NOW = datetime(2026, 11, 12, 3, 0, 0, tzinfo=UTC)
INSTANCE_ID = "si-expectation"


def _instance(
    *, inst_ids: tuple[str, ...] = ("BTC-USDT",), version: str = "1.0.0"
) -> InstanceRecord:
    return InstanceRecord(
        instance_id=INSTANCE_ID,
        strategy_id="relative_value",
        strategy_version=version,
        name="BTC 相对价值",
        bar="1d",
        params={},
        inst_ids=inst_ids,
        lifecycle_status="paper_trading",
        enabled=True,
        execution_mode="paper",
        latest_signal_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _run(
    *,
    run_id: str,
    inst_id: str,
    created_at: int,
    total_return: str,
    version: str = "1.0.0",
) -> BacktestRunRow:
    return BacktestRunRow(
        run_id=run_id,
        strategy_instance_id=INSTANCE_ID,
        strategy_id="relative_value",
        strategy_version=version,
        params_json="{}",
        bar="1d",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 10),
        data_source="okx_spot",
        inst_id=inst_id,
        inst_type="SPOT",
        request_json="{}",
        data_fingerprint="fingerprint",
        execution_model="next_open",
        costs_json="{}",
        metrics_json=f'{{"total_return": {total_return}}}',
        portfolio_json="{}",
        funding_total=Decimal("0"),
        result_hash=f"hash-{run_id}",
        created_at=created_at,
    )


def test_latest_expectation_uses_current_instruments_and_version(client: TestClient) -> None:
    """更晚但标的不在实例集合内、或版本不一致的运行都不算预期。"""

    with session_scope() as session:
        session.add_all(
            [
                _run(run_id="older", inst_id="BTC-USDT", created_at=100, total_return="0.10"),
                _run(run_id="newest", inst_id="BTC-USDT", created_at=200, total_return="0.20"),
                _run(run_id="other-leg", inst_id="ETH-USDT", created_at=300, total_return="0.30"),
                _run(
                    run_id="old-version",
                    inst_id="BTC-USDT",
                    created_at=400,
                    total_return="0.40",
                    version="0.9.0",
                ),
            ]
        )

    value, source = latest_expectations([_instance()])[INSTANCE_ID]

    assert value == Decimal("0.20")
    assert source == "backtest:newest:BTC-USDT:1.0.0:metrics.total_return"


def test_latest_expectation_is_absent_without_a_matching_run(client: TestClient) -> None:
    """实例改过标的集合后，旧标的上的回测不再被当成当前预期。"""

    with session_scope() as session:
        session.add(_run(run_id="btc-run", inst_id="BTC-USDT", created_at=100, total_return="0.10"))

    assert latest_expectations([_instance(inst_ids=("ETH-USDT",))]) == {}
