"""回测 API 契约：幂等、无未来数据、只认已确认 bar、错误码与报告（AC3/4/5/7/9/10/11）。"""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import IntegrityError

from app.backtest import service
from app.backtest.models import BacktestMetric, BacktestRun
from app.jobs import tasks
from app.market.models import Candle
from app.ops.models import JobRun
from app.strategy.models import Strategy
from tests.backtest.support import at, seed_candles, seed_strategy
from tests.market.support import insert_instrument

START = at(1)
END = at(11)


def iso(moment) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def payload(strategy_id: int, **overrides) -> dict:
    body = {
        "strategy_id": strategy_id,
        "window": {"start": iso(START), "end": iso(END)},
        "bar": "1d",
        "initial_capital": "100000",
        "cost_model": {
            "taker_fee_bps": "5",
            "maker_fee_bps": "2",
            "slippage_bps": "2",
            "funding_bps_per_period": "1",
        },
    }
    body.update(overrides)
    return body


async def seed_book(session, *, status: str = "approved"):
    aapl = await insert_instrument(session, "AAPL-USDT-SWAP")
    nvda = await insert_instrument(session, "NVDA-USDT-SWAP")
    await seed_candles(
        session,
        aapl.id,
        start=START,
        prices=["100", "102", "101", "105", "108", "107", "110", "112", "111", "115"],
    )
    await seed_candles(
        session,
        nvda.id,
        start=START,
        prices=["50", "51", "49", "52", "53", "52", "54", "55", "54", "56"],
    )
    strategy = await seed_strategy(
        session,
        [(aapl.id, "long", "0.5"), (nvda.id, "short", "-0.5")],
        status=status,
    )
    return strategy, aapl, nvda


async def submit(client, strategy_id: int, **overrides):
    response = await client.post("/api/v1/backtests", json=payload(strategy_id, **overrides))
    return response


async def run_job(session, dispatched) -> int:
    assert dispatched, "task was not dispatched"
    call = dispatched[-1]
    assert call["task_name"] == tasks.BACKTEST_RUN
    await service.execute(session, int(call["backtest_id"]))
    return int(call["backtest_id"])


def metric_values(items) -> dict[str, str]:
    return {item["name"]: item["value"] for item in items}


async def test_same_parameters_return_same_run_and_single_job(client, session, dispatched) -> None:
    strategy, _, _ = await seed_book(session)

    first = await submit(client, strategy.id)
    assert first.status_code == 202
    body = first.json()
    assert body["created"] is True
    assert body["dispatched"] is True
    assert body["status"] == "queued"
    assert len(dispatched) == 1

    second = await submit(client, strategy.id)
    assert second.status_code == 200
    assert second.json()["run_id"] == body["run_id"]
    assert second.json()["job_id"] == body["job_id"]
    assert second.json()["created"] is False
    assert second.json()["dispatched"] is False
    assert len(dispatched) == 1

    total = await session.scalar(select(func.count()).select_from(JobRun))
    assert total == 1


async def test_concurrent_same_parameters_stay_idempotent(client, session, dispatched) -> None:
    """并发同参数提交：只建 1 run / 1 job，全部返回统一响应，不出现 500。"""

    strategy, _, _ = await seed_book(session)
    responses = await asyncio.gather(
        *[client.post("/api/v1/backtests", json=payload(strategy.id)) for _ in range(4)]
    )
    assert sorted(response.status_code for response in responses) == [200, 200, 200, 202]
    bodies = [response.json() for response in responses]
    assert len({body["run_id"] for body in bodies}) == 1
    assert len({body["job_id"] for body in bodies}) == 1
    assert sum(1 for body in bodies if body["dispatched"]) == 1
    assert len(dispatched) == 1

    runs = await session.scalar(select(func.count()).select_from(BacktestRun))
    jobs = await session.scalar(select(func.count()).select_from(JobRun))
    assert (runs, jobs) == (1, 1)


async def test_failed_run_is_retried_by_same_parameters(client, session, dispatched) -> None:
    """失败后同参数再提交：job 与 run 同步复位为 queued 并重新投递（评审阻断 1）。"""

    strategy, _, _ = await seed_book(session)
    strategy_id = strategy.id
    accepted = (await submit(client, strategy_id)).json()
    run_id = await run_job(session, dispatched)
    assert accepted["run_id"] == run_id

    session.expire_all()
    run = await session.get(BacktestRun, run_id)
    assert run is not None
    await session.refresh(run)
    run.status = "failed"
    run.error = "boom"
    job = await session.get(JobRun, accepted["job_id"])
    assert job is not None
    job.status = "failed"
    await session.commit()

    retried = await submit(client, strategy_id)
    assert retried.status_code == 202
    body = retried.json()
    assert body["run_id"] == run_id
    assert body["created"] is False
    assert body["dispatched"] is True
    assert body["status"] == "queued"
    assert len(dispatched) == 2

    session.expire_all()
    requeued = await session.get(BacktestRun, run_id)
    assert requeued is not None
    await session.refresh(requeued)
    assert requeued.status == "queued"
    assert requeued.error is None
    requeued_job = await session.get(JobRun, accepted["job_id"])
    assert requeued_job is not None
    await session.refresh(requeued_job)
    assert requeued_job.status == "queued"

    assert await run_job(session, dispatched) == run_id
    detail = (await client.get(f"/api/v1/backtests/{run_id}")).json()
    assert detail["status"] == "ok"


async def test_persist_failure_converges_to_failed_and_session_stays_usable(
    client, session, dispatched, monkeypatch
) -> None:
    """落库失败必须收敛为 failed，且不能把会话留在 aborted 状态（评审阻断 2）。"""

    strategy, _, _ = await seed_book(session)
    await submit(client, strategy.id)
    run_id = int(dispatched[-1]["backtest_id"])

    async def broken_persist(db, *, run, simulation, metrics):
        await db.execute(
            insert(BacktestMetric),
            [
                {"run_id": run.id, "name": "dup", "value": Decimal(1), "unit": "ratio"},
                {"run_id": run.id, "name": "dup", "value": Decimal(2), "unit": "ratio"},
            ],
        )

    monkeypatch.setattr(service, "_persist", broken_persist)
    with pytest.raises(IntegrityError):
        await service.execute(session, run_id)

    await session.rollback()
    assert await session.scalar(text("SELECT 1")) == 1

    detail = (await client.get(f"/api/v1/backtests/{run_id}")).json()
    assert detail["status"] == "failed"
    assert "IntegrityError" in (detail["error"] or "")


async def test_report_metrics_equity_and_trades_match_run(client, session, dispatched) -> None:
    strategy, _, _ = await seed_book(session)
    accepted = (await submit(client, strategy.id)).json()
    run_id = await run_job(session, dispatched)
    assert run_id == accepted["run_id"]

    detail = (await client.get(f"/api/v1/backtests/{run_id}")).json()
    assert detail["status"] == "ok"
    assert detail["strategy_version"] == 1
    assert detail["funding_assumption"] == "constant"
    assert detail["params"]["price_basis"] == "okx_close"

    metrics = (await client.get(f"/api/v1/backtests/{run_id}/metrics")).json()
    assert len(metrics["items"]) == 10
    assert metrics["funding_assumption"] == "constant"
    assert set(metric_values(metrics["items"])) == {
        "total_return",
        "annualized_return",
        "max_drawdown",
        "sharpe",
        "sortino",
        "win_rate",
        "profit_loss_ratio",
        "trade_count",
        "turnover",
        "cost_ratio",
    }
    assert metrics["items"][0]["unit"] in {"ratio", "count"}

    equity = (await client.get(f"/api/v1/backtests/{run_id}/equity?limit=40")).json()
    assert len(equity["items"]) == 10
    assert equity["items"][0]["ts"] == iso(START)
    assert equity["items"][-1]["drawdown"] is not None

    trades = (await client.get(f"/api/v1/backtests/{run_id}/trades")).json()
    assert len(trades["items"]) == 2
    sides = {item["side"] for item in trades["items"]}
    assert sides == {"long", "short"}
    for item in trades["items"]:
        expected = Decimal(item["gross_pnl"]) - Decimal(item["fees"]) - Decimal(item["funding"])
        assert abs(Decimal(item["net_pnl"]) - expected) < Decimal("1e-6")
        assert item["exit_reason"] == "window_end"


async def test_pagination_uses_cursor(client, session, dispatched) -> None:
    strategy, _, _ = await seed_book(session)
    await submit(client, strategy.id)
    run_id = await run_job(session, dispatched)

    first = (await client.get(f"/api/v1/backtests/{run_id}/equity?limit=3")).json()
    assert len(first["items"]) == 3
    assert first["next_cursor"] is not None
    second = (
        await client.get(f"/api/v1/backtests/{run_id}/equity?limit=3&cursor={first['next_cursor']}")
    ).json()
    assert second["items"][0]["ts"] > first["items"][-1]["ts"]

    trades = (await client.get(f"/api/v1/backtests/{run_id}/trades?limit=1")).json()
    assert len(trades["items"]) == 1
    assert trades["next_cursor"] is not None


async def test_results_ignore_future_and_unconfirmed_bars(client, session, dispatched) -> None:
    strategy, aapl, _ = await seed_book(session)
    await submit(client, strategy.id)
    run_id = await run_job(session, dispatched)
    baseline = metric_values(
        (await client.get(f"/api/v1/backtests/{run_id}/metrics")).json()["items"]
    )

    extreme = Decimal("10000")
    session.add_all(
        [
            # 窗口内但未确认：必须被排除并登记，不得影响结果。
            Candle(
                instrument_id=aapl.id,
                bar="1d",
                open_time=at(3, hour=12),
                open=extreme,
                high=extreme,
                low=extreme,
                close=extreme,
                vol=Decimal(1),
                vol_ccy=Decimal(1),
                vol_ccy_quote=Decimal(1),
                confirm=False,
                source="test",
            ),
            # 窗口结束后且极端：引擎永远看不到。
            Candle(
                instrument_id=aapl.id,
                bar="1d",
                open_time=END + timedelta(hours=12),
                open=extreme,
                high=extreme,
                low=extreme,
                close=extreme,
                vol=Decimal(1),
                vol_ccy=Decimal(1),
                vol_ccy_quote=Decimal(1),
                confirm=True,
                source="test",
            ),
        ]
    )
    await session.commit()

    await service.execute(session, run_id)
    after = metric_values((await client.get(f"/api/v1/backtests/{run_id}/metrics")).json()["items"])
    assert after == baseline

    detail = (await client.get(f"/api/v1/backtests/{run_id}")).json()
    assert detail["params"]["excluded_incomplete"] == {str(aapl.id): 1}


async def test_multi_window_metrics_have_suffixes_and_aggregate(
    client, session, dispatched
) -> None:
    strategy, _, _ = await seed_book(session)
    windows = [
        {
            "name": "w1",
            "start": iso(at(1)),
            "end": iso(at(5)),
            "role": "train",
        },
        {
            "name": "w2",
            "start": iso(at(6)),
            "end": iso(at(11)),
            "role": "test",
        },
    ]
    response = await submit(client, strategy.id, windows=windows)
    assert response.status_code == 202
    run_id = await run_job(session, dispatched)

    names = set(
        metric_values((await client.get(f"/api/v1/backtests/{run_id}/metrics")).json()["items"])
    )
    assert {"sharpe", "sharpe@w1", "sharpe@w2", "total_return@w1", "total_return@w2"} <= names


async def test_criteria_failure_is_still_readable_and_archive_keeps_verdict(
    client, session, dispatched
) -> None:
    strategy, _, _ = await seed_book(session)
    criteria = {"thresholds": [{"name": "total_return", "op": ">=", "value": "999"}]}
    await submit(client, strategy.id, criteria=criteria)
    run_id = await run_job(session, dispatched)

    detail = (await client.get(f"/api/v1/backtests/{run_id}")).json()
    assert detail["criteria"]["passed"] is False
    assert detail["criteria"]["default"] is False
    assert detail["criteria"]["results"][0]["actual"] is not None
    assert (await client.get(f"/api/v1/backtests/{run_id}/metrics")).status_code == 200

    strategy_row = await session.get(Strategy, strategy.id)
    strategy_row.status = "archived"
    await session.commit()
    unchanged = (await client.get(f"/api/v1/backtests/{run_id}")).json()
    assert unchanged["criteria"]["passed"] is False


async def test_default_criteria_marks_default_true(client, session, dispatched) -> None:
    strategy, _, _ = await seed_book(session)
    await submit(client, strategy.id)
    run_id = await run_job(session, dispatched)
    detail = (await client.get(f"/api/v1/backtests/{run_id}")).json()
    assert detail["criteria"]["default"] is True
    assert detail["criteria"]["passed"] in (True, False)


async def test_non_approved_strategy_is_rejected(client, session, dispatched) -> None:
    strategy, _, _ = await seed_book(session, status="pending_approval")
    response = await submit(client, strategy.id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "strategy_not_approved"
    assert dispatched == []


async def test_missing_confirmed_bars_returns_gaps(client, session, dispatched) -> None:
    strategy, _, _ = await seed_book(session)
    tsla = await insert_instrument(session, "TSLA-USDT-SWAP")
    await seed_candles(session, tsla.id, start=at(100), prices=["200", "201"])
    # 缺少窗口内已确认 bar 的腿：直接追加到策略里。
    from app.strategy.models import StrategyLeg

    session.add(
        StrategyLeg(
            strategy_id=strategy.id,
            instrument_id=tsla.id,
            side="long",
            target_weight=Decimal("0.1"),
            rationale="gap",
            rank=2,
        )
    )
    await session.commit()

    response = await submit(client, strategy.id)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "insufficient_data"
    assert error["details"]["gaps"][0]["instrument_id"] == tsla.id
    assert dispatched == []


async def test_invalid_inputs_never_500(client, session, dispatched) -> None:
    strategy, _, _ = await seed_book(session)

    bad_bar = await submit(client, strategy.id, bar="3h")
    assert bad_bar.status_code == 422
    assert bad_bar.json()["error"]["code"] == "backtest_invalid_bar"

    empty = await submit(
        client,
        strategy.id,
        window={"start": iso(END), "end": iso(START)},
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "backtest_window_invalid"

    too_long = await submit(
        client,
        strategy.id,
        window={"start": "1900-01-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"},
    )
    assert too_long.status_code == 422
    assert too_long.json()["error"]["code"] == "backtest_window_too_long"

    unknown = await client.get("/api/v1/backtests/999999")
    assert unknown.status_code == 404
    assert (await client.get("/api/v1/backtests/999999/metrics")).status_code == 404
    assert (await client.get("/api/v1/backtests/999999/equity")).status_code == 404
    assert (await client.get("/api/v1/backtests/999999/trades")).status_code == 404
