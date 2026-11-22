"""宏观测试的公共夹具：假 provider、运行时重置与落库辅助。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

from app.core import Observation
from app.macro.config import SeriesUnit
from app.macro.store import ObservationRecord, save_observations


class FakeProvider:
    """可控的上游：返回预设观测，记录每次 `fetch` 的入参。"""

    def __init__(self, name: str, values: dict[str, list[Observation]]) -> None:
        self.name = name
        self.values = values
        self.calls: list[tuple[str, ...]] = []

    def supports(self, series: Sequence[str]) -> bool:
        return all(item in self.values for item in series)

    def fetch(self, series: Sequence[str], since: datetime | None) -> list[Observation]:
        self.calls.append(tuple(series))
        lower = None if since is None else int(since.timestamp())
        found: list[Observation] = []
        for series_id in series:
            for item in self.values.get(series_id, []):
                # 真实 provider 只产出来自自己的行；替身同样只交出自己那份。
                if item.provider != self.name:
                    continue
                if lower is None or item.ts >= lower:
                    found.append(item)
        return found


def observation(
    series_id: str,
    *,
    ts: int,
    value: str,
    provider: str,
    is_delayed: bool = False,
) -> Observation:
    from decimal import Decimal

    return Observation(
        series_id=series_id,
        ts=ts,
        value=Decimal(value),
        provider=provider,
        is_delayed=is_delayed,
    )


def seed(
    series_id: str,
    *,
    ts: int,
    value: str,
    provider: str,
    trading_day: date,
    market_session: str = "closed",
    is_delayed: bool = False,
) -> None:
    """直接落一条观测，绕过 provider：用于只读路径与利差口径的用例。"""

    saved = save_observations(
        [
            ObservationRecord(
                observation=observation(
                    series_id,
                    ts=ts,
                    value=value,
                    provider=provider,
                    is_delayed=is_delayed,
                ),
                trading_day=trading_day,
                market_session=market_session,
            )
        ],
        now=datetime(2026, 11, 22, 7, 0, tzinfo=UTC),
    )
    assert saved == 1


def provider_builder(values: dict[str, list[Observation]]):
    """一份数据 → 按 provider 名各造一个替身的 builder。"""

    return lambda name, **_: FakeProvider(name, values)


def unit(series_id: str, granularity: str, provider: str) -> SeriesUnit:
    return SeriesUnit(series_id=series_id, granularity=granularity, provider=provider)
