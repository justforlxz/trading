"""关系快照、显著变化与相对强弱的 HTTP 契约（AC4 / AC5 / AC6 / AC7 / AC8）。"""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.api.v1 import research as research_api
from app.config import get_settings
from app.jobs import tasks
from app.research.models import RelationEdge, RelationSnapshot
from tests.market.support import insert_instrument
from tests.research.support import START, inverted, seed_equity_series, seed_okx_series, wave


@pytest.fixture
def inline_dispatch(monkeypatch):
    """把后台投递换成同进程同步执行：202 返回时快照已经落库。"""

    calls: list[tuple[str, dict]] = []

    async def fake(task_name: str, **kwargs):
        calls.append((task_name, kwargs))
        await getattr(tasks, task_name)({}, **kwargs)

    monkeypatch.setattr(research_api, "dispatch", fake)
    return calls


async def _create_target(client, symbol: str = "AAPL", exchange: str = "XNAS") -> dict:
    response = await client.post("/api/v1/targets", json={"symbol": symbol, "exchange": exchange})
    assert response.status_code == 201
    return response.json()


async def _recompute(client, target_id: int, **body):
    return await client.post(f"/api/v1/targets/{target_id}/relations/recompute", json=body)


async def _job(client, job_id: int) -> dict:
    response = await client.get(f"/api/v1/ops/job-runs/{job_id}")
    assert response.status_code == 200
    return response.json()


def _iso(days: int) -> str:
    return (START + timedelta(days=days)).isoformat()


async def _seed_correlated(session) -> None:
    base = wave(80)
    await seed_okx_series(
        session,
        {
            "AAPL-USDT-SWAP": base,
            "SPY-USDT-SWAP": wave(80, offset=400.0, amplitude=8.0),
            "QQQ-USDT-SWAP": wave(80, offset=300.0, amplitude=6.0, step=0.55),
        },
    )


async def test_recompute_stores_snapshot_and_edges(client, session, inline_dispatch):
    await _seed_correlated(session)
    target = await _create_target(client)

    response = await _recompute(client, target["id"], window_bars=60)

    assert response.status_code == 202
    assert response.json()["job_name"] == tasks.RECOMPUTE_RELATIONS
    assert response.headers["location"].startswith("/api/v1/ops/job-runs/")

    detail = (await client.get(f"/api/v1/targets/{target['id']}/relations")).json()
    assert detail["status"] == "ok"
    snapshot = detail["snapshot"]
    assert snapshot["price_basis"] == "okx_close"
    assert snapshot["method"] == "pearson"
    assert snapshot["window_bars"] == 60
    assert snapshot["lag_max"] == get_settings().relation_lag_max
    assert snapshot["sample_size"] > 0

    assert len(detail["edges"]) >= 2
    edge = detail["edges"][0]
    assert {
        "counterparty_inst_id",
        "coefficient",
        "best_lag",
        "p_value",
        "stability",
        "rank",
    } <= set(edge)
    assert isinstance(edge["coefficient"], str)


async def test_same_parameters_are_skipped_and_do_not_duplicate(client, session, inline_dispatch):
    await _seed_correlated(session)
    target = await _create_target(client)

    first = await _recompute(client, target["id"], window_bars=60)
    second = await _recompute(client, target["id"], window_bars=60)

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["status"] == "skipped"
    count = await session.scalar(select(func.count()).select_from(RelationSnapshot))
    assert count == 1


async def test_sign_flip_is_reported_as_significant_change(client, session, inline_dispatch):
    base = wave(120)
    spy = base[:60] + inverted(base[60:])
    await seed_okx_series(session, {"AAPL-USDT-SWAP": base, "SPY-USDT-SWAP": spy})
    target = await _create_target(client)

    first = await _recompute(client, target["id"], window_bars=30, as_of=_iso(29))
    second = await _recompute(client, target["id"], window_bars=30, as_of=_iso(89))
    assert first.status_code == 202
    assert second.status_code == 202

    detail = (await client.get(f"/api/v1/targets/{target['id']}/relations")).json()
    assert detail["status"] == "ok"
    spy_edge = next(e for e in detail["edges"] if e["counterparty_inst_id"] == "SPY-USDT-SWAP")
    assert float(spy_edge["coefficient"]) < -0.99

    flip = next(c for c in detail["significant_changes"] if c["counterparty"] == "SPY-USDT-SWAP")
    assert flip["sign_flip"] is True
    assert flip["significant"] is True


async def test_change_threshold_is_configurable(client, session, monkeypatch):
    target = await _create_target(client)
    spy = await insert_instrument(session, "SPY-USDT-SWAP")
    first = RelationSnapshot(
        target_id=target["id"],
        as_of=START,
        window_bars=60,
        method="pearson",
        price_basis="okx_close",
        lag_max=5,
        sample_size=60,
        run_key="threshold-a",
        params={},
    )
    second = RelationSnapshot(
        target_id=target["id"],
        as_of=START + timedelta(days=1),
        window_bars=60,
        method="pearson",
        price_basis="okx_close",
        lag_max=5,
        sample_size=60,
        run_key="threshold-b",
        params={},
    )
    session.add_all([first, second])
    await session.commit()
    session.add_all(
        [
            RelationEdge(
                snapshot_id=first.id,
                counterparty_id=spy.id,
                coefficient=Decimal("0.5"),
                best_lag=0,
                p_value=Decimal("0.1"),
                stability=Decimal("0.8"),
                rank=1,
            ),
            RelationEdge(
                snapshot_id=second.id,
                counterparty_id=spy.id,
                coefficient=Decimal("0.75"),
                best_lag=0,
                p_value=Decimal("0.1"),
                stability=Decimal("0.8"),
                rank=1,
            ),
        ]
    )
    await session.commit()

    default_view = (await client.get(f"/api/v1/targets/{target['id']}/relations")).json()
    assert [c["counterparty"] for c in default_view["significant_changes"]] == ["SPY-USDT-SWAP"]
    assert default_view["significant_changes"][0]["delta"] == pytest.approx(0.25)

    loose = get_settings().model_copy(update={"relation_change_threshold": 0.5})
    monkeypatch.setattr(research_api, "get_settings", lambda: loose)
    strict_view = (await client.get(f"/api/v1/targets/{target['id']}/relations")).json()
    assert strict_view["significant_changes"] == []


async def test_threshold_change_on_same_as_of_is_skipped_not_failed(
    client, session, inline_dispatch, monkeypatch
):
    """改配置后同 as_of 重算：run_key 只含口径身份，不会撞第二条唯一约束。"""

    await _seed_correlated(session)
    target = await _create_target(client)

    first = await _recompute(client, target["id"], window_bars=60, as_of=_iso(59))
    assert first.status_code == 202

    changed = get_settings().model_copy(update={"relation_change_threshold": 0.9})
    monkeypatch.setattr(research_api, "get_settings", lambda: changed)
    monkeypatch.setattr(tasks, "get_settings", lambda: changed)
    second = await _recompute(client, target["id"], window_bars=60, as_of=_iso(59))

    assert second.status_code == 202
    job = await _job(client, second.json()["job_id"])
    assert job["status"] == "skipped"
    assert job["error"] is None
    count = await session.scalar(select(func.count()).select_from(RelationSnapshot))
    assert count == 1


async def test_target_without_instrument_id_never_self_correlates(client, session, inline_dispatch):
    """目标先建（instrument_id 为空）后补行情：候选集仍按 symbol 排除目标自身。"""

    target = await _create_target(client)
    assert target["instrument_id"] is None

    base = wave(80)
    await seed_okx_series(
        session,
        {
            "AAPL-USDT-SWAP": base,
            "SPY-USDT-SWAP": wave(80, offset=400.0, amplitude=8.0, step=0.9),
        },
    )

    response = await _recompute(client, target["id"], window_bars=60)
    assert response.status_code == 202

    detail = (await client.get(f"/api/v1/targets/{target['id']}/relations")).json()
    assert detail["status"] == "ok"
    counterparts = {edge["counterparty_inst_id"] for edge in detail["edges"]}
    assert "AAPL-USDT-SWAP" not in counterparts
    assert all(abs(float(edge["coefficient"])) < 0.999 for edge in detail["edges"])


async def test_history_lists_snapshots(client, session, inline_dispatch):
    await _seed_correlated(session)
    target = await _create_target(client)
    await _recompute(client, target["id"], window_bars=60)

    response = await client.get(f"/api/v1/targets/{target['id']}/relations/history")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["edge_count"] >= 2
    assert items[0]["significant_changes"] == []


async def test_recompute_without_okx_candles_reports_missing_source(client, inline_dispatch):
    target = await _create_target(client, symbol="TSLA")

    response = await _recompute(client, target["id"], window_bars=60)

    assert response.status_code == 202
    job = await _job(client, response.json()["job_id"])
    assert job["status"] == "partial"
    assert "MISSING_SOURCE" in job["result"]["reason"]

    detail = (await client.get(f"/api/v1/targets/{target['id']}/relations")).json()
    assert detail["status"] == "undefined"
    assert detail["reason"]
    assert detail["snapshot"] is None
    assert detail["edges"] == []


async def test_equity_close_without_real_data_does_not_fake_prices(
    client, session, inline_dispatch
):
    await seed_okx_series(session, {"AAPL-USDT-SWAP": wave(80)})
    target = await _create_target(client)

    response = await _recompute(client, target["id"], window_bars=60, price_basis="equity_close")

    assert response.status_code == 202
    job = await _job(client, response.json()["job_id"])
    assert "MISSING_SOURCE" in job["result"]["reason"]
    assert "equity_close" in job["result"]["reason"]
    count = await session.scalar(select(func.count()).select_from(RelationSnapshot))
    assert count == 0


async def test_relative_strength_okx_series_is_defined(client, session):
    await seed_okx_series(
        session, {"AAPL-USDT-SWAP": wave(60), "SPY-USDT-SWAP": wave(60, offset=300.0)}
    )
    target = await _create_target(client)

    response = await client.get(
        f"/api/v1/targets/{target['id']}/relative-strength",
        params={"counterparty": "SPY-USDT-SWAP", "lookback": 60},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["defined"] is True
    assert body["reason"] is None
    assert Decimal(body["rs_ratio"]) > 0
    assert body["excess_return"] is not None
    assert len(body["series"]) > 0


async def test_relative_strength_insufficient_window_has_reason(client, session):
    await seed_okx_series(session, {"AAPL-USDT-SWAP": wave(60), "SPY-USDT-SWAP": wave(1)})
    target = await _create_target(client)

    body = (
        await client.get(
            f"/api/v1/targets/{target['id']}/relative-strength",
            params={"counterparty": "SPY-USDT-SWAP", "lookback": 60},
        )
    ).json()

    assert body["defined"] is False
    assert body["reason"]


async def test_relative_strength_uses_equity_close_when_available(client, session):
    await seed_equity_series(session, {"AAPL": wave(40), "SPY": wave(40, offset=300.0)})
    await seed_okx_series(session, {"SPY-USDT-SWAP": wave(40)})
    target = await _create_target(client)

    body = (
        await client.get(
            f"/api/v1/targets/{target['id']}/relative-strength",
            params={
                "counterparty": "SPY-USDT-SWAP",
                "lookback": 40,
                "price_basis": "equity_close",
            },
        )
    ).json()

    assert body["defined"] is True
    assert body["price_basis"] == "equity_close"


async def test_unknown_target_and_counterparty_return_404(client):
    relations = await client.get("/api/v1/targets/987654/relations")
    assert relations.status_code == 404
    assert relations.json()["error"]["code"] == "TARGET_NOT_FOUND"

    target = await _create_target(client)
    strength = await client.get(
        f"/api/v1/targets/{target['id']}/relative-strength",
        params={"counterparty": "NOPE-USDT-SWAP"},
    )
    assert strength.status_code == 404
    assert strength.json()["error"]["code"] == "INSTRUMENT_NOT_FOUND"
