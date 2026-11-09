"""MCP resources:`strategy://{id}`,`backtest://{id}`,`market://snapshot`.

资源是「按 URI 读一段快照」的只读通道,和工具一样不做任何计算,
只把既有 service 的结果原样整理成 JSON 文本.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest import service as backtest_service
from app.opportunity import query as opportunity_query
from app.strategy import service as strategy_service

MIME_JSON = "application/json"

PREFIX_STRATEGY = "strategy://"
PREFIX_BACKTEST = "backtest://"
URI_MARKET = "market://snapshot"


def resource_list() -> list[dict[str, str]]:
    return [
        {
            "uri": URI_MARKET,
            "name": "market_snapshot",
            "description": "全市场最新特征截面(扫描产物,含广度与交易时段)",
            "mimeType": MIME_JSON,
        },
        {
            "uri": "strategy://{id}",
            "name": "strategy",
            "description": "单条策略详情(与 GET /api/v1/strategies/{id} 字段一致)",
            "mimeType": MIME_JSON,
        },
        {
            "uri": "backtest://{id}",
            "name": "backtest",
            "description": "单次回测的运行信息与指标",
            "mimeType": MIME_JSON,
        },
    ]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


async def backtest_payload(session: AsyncSession, backtest_id: int) -> dict[str, Any]:
    """回测运行 + 指标;运行不存在时由 `backtest_service.get_run` 抛 404 域错误."""

    run = await backtest_service.get_run(session, backtest_id)
    metrics = await backtest_service.load_metrics(session, backtest_id)
    params = run.params or {}
    return {
        "id": run.id,
        "run_key": run.run_key,
        "strategy_id": run.strategy_id,
        "strategy_version": run.strategy_version,
        "window": {"start": _iso(run.window_start), "end": _iso(run.window_end)},
        "bar": run.bar,
        "initial_capital": _text(run.initial_capital),
        "status": run.status,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "error": run.error,
        "criteria": params.get("criteria"),
        "funding_assumption": params.get("funding_assumption"),
        "metrics": [
            {"name": row.name, "value": _text(row.value), "unit": row.unit} for row in metrics
        ],
    }


def _parse_id(uri: str, prefix: str) -> int:
    raw = uri[len(prefix) :].strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{prefix}{{id}} expects an integer id, got {uri!r}") from error
    if value <= 0:
        raise ValueError(f"{prefix}{{id}} expects a positive id, got {uri!r}")
    return value


async def read_resource(session: AsyncSession, uri: str) -> dict[str, Any]:
    """读取一个资源;未知 URI 抛 `ValueError`(调用方转成 -32602)."""

    if uri == URI_MARKET:
        payload = await opportunity_query.market_snapshot_view(session)
    elif uri.startswith(PREFIX_STRATEGY):
        payload = await strategy_service.strategy_detail(session, _parse_id(uri, PREFIX_STRATEGY))
    elif uri.startswith(PREFIX_BACKTEST):
        payload = await backtest_payload(session, _parse_id(uri, PREFIX_BACKTEST))
    else:
        raise ValueError(f"unknown resource uri: {uri}")
    return {
        "uri": uri,
        "mimeType": MIME_JSON,
        "text": json.dumps(payload, ensure_ascii=False, default=str),
    }


__all__ = [
    "MIME_JSON",
    "URI_MARKET",
    "backtest_payload",
    "read_resource",
    "resource_list",
]
