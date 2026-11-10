"""假 OKX 的内存数据源。

标的清单来自冻结快照；K 线、资金费与行情快照按标的名确定性生成，无需预置数据。
业务错误用 `OkxApiError` 表达（HTTP 200 + 非零 code），与限流/上游故障区分。
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from tests.factories.candles import (
    align_open_time,
    bar_seconds,
    make_candle_rows,
    make_ticker_row,
)
from tests.factories.instruments import load_instruments

UNKNOWN_INST_ID_CODE = "51001"
INVALID_PARAMETER_CODE = "51000"
MAX_CANDLE_LIMIT = 100
SUPPORTED_INST_TYPES = frozenset({"SPOT", "SWAP"})

# 资金费按 8 小时结算：00/08/16 UTC。
FUNDING_INTERVAL_SECONDS = 8 * 3600
# 假历史保留 360 期（约 4 个月）：按每页 100 条要翻满 4 页才到底，
# 既覆盖「多页回溯」，又不构造真实上游没有的多年数据。
FUNDING_HISTORY_DEPTH = 360


def align_funding_time(timestamp: int) -> int:
    """把时间戳对齐到 8 小时结算网格。"""

    return timestamp - timestamp % FUNDING_INTERVAL_SECONDS


def make_funding_row(inst_id: str, funding_time: int) -> dict[str, str]:
    """构造一期资金费行，字段与 OKX `/public/funding-rate-history` 一致。

    费率由 `sha256(inst_id|funding_time)` 派生，跨进程稳定；约 1/7 的结算期
    `realizedRate` 是 `"0"`，用来区分「真实为 0」与「上游没给」。
    """

    seed = int.from_bytes(hashlib.sha256(f"{inst_id}|{funding_time}".encode()).digest()[:8], "big")
    rate = (Decimal(seed % 2001 - 1000) / Decimal(1_000_000)).quantize(Decimal("1E-8"))
    return {
        "instType": "SWAP",
        "instId": inst_id,
        "fundingRate": format(rate, "f"),
        "realizedRate": "0" if seed % 7 == 0 else format(rate, "f"),
        "fundingTime": str(funding_time * 1000),
        "method": "current_period",
    }


class OkxApiError(Exception):
    """上游业务错误：HTTP 200 + 非零 code。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OkxStore:
    """假 OKX 的全部数据来源。"""

    def __init__(
        self,
        *,
        instruments: Sequence[dict[str, Any]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        rows = list(instruments) if instruments is not None else load_instruments()
        self._instruments = rows
        self._by_inst_id = {row["instId"]: row for row in rows}
        self._clock = clock

    def instruments(self, inst_type: str) -> list[dict[str, Any]]:
        """按产品类型返回标的元数据。"""

        if inst_type not in SUPPORTED_INST_TYPES:
            raise OkxApiError(INVALID_PARAMETER_CODE, f"Parameter instType error:{inst_type!r}")
        return [row for row in self._instruments if row["instType"] == inst_type]

    def candles(self, inst_id: str, bar: str, limit: int) -> list[list[str]]:
        """最近 `limit` 根 K 线，倒序（最新在前），最新一根未收盘。"""

        self._require_inst_id(inst_id)
        self._validate_bar(bar)
        self._validate_limit(limit)
        return make_candle_rows(
            inst_id,
            bar,
            count=limit,
            end_time=int(self._clock()),
            include_incomplete=True,
        )

    def history_candles(
        self,
        inst_id: str,
        bar: str,
        *,
        after: int | None = None,
        limit: int = MAX_CANDLE_LIMIT,
    ) -> list[list[str]]:
        """历史 K 线；`after` 是秒级时间戳，只返回严格早于它的已完成 K 线。

        上游用毫秒传游标，由 `app` 层换算后再进来，避免这里出现两套单位。
        """

        self._require_inst_id(inst_id)
        self._validate_bar(bar)
        self._validate_limit(limit)
        if after is None:
            return self.candles(inst_id, bar, limit)
        newest = align_open_time(after, bar) - bar_seconds(bar)
        return make_candle_rows(
            inst_id,
            bar,
            count=limit,
            end_time=newest,
            include_incomplete=False,
        )

    def ticker(self, inst_id: str) -> dict[str, str]:
        """最新行情快照。"""

        row = self._require_inst_id(inst_id)
        return make_ticker_row(inst_id, inst_type=row["instType"], ts=int(self._clock()))

    def funding_rate_history(
        self,
        inst_id: str,
        *,
        after: int | None = None,
        limit: int = MAX_CANDLE_LIMIT,
    ) -> list[dict[str, str]]:
        """资金费历史；`after` 是秒级时间戳，只返回严格早于它的记录（倒序）。

        只有永续合约有资金费，现货按上游规则报参数错误。历史深度固定：
        翻到最早一期之后返回空页，与真实上游「老标的也只有一个起点」一致。
        """

        row = self._require_inst_id(inst_id)
        if row["instType"] != "SWAP":
            raise OkxApiError(
                INVALID_PARAMETER_CODE, f"Instrument ID does not have funding:{inst_id}"
            )
        self._validate_limit(limit)
        latest = align_funding_time(int(self._clock()))
        earliest = latest - (FUNDING_HISTORY_DEPTH - 1) * FUNDING_INTERVAL_SECONDS
        if after is not None:
            latest = min(latest, align_funding_time(after) - FUNDING_INTERVAL_SECONDS)
        count = (latest - earliest) // FUNDING_INTERVAL_SECONDS + 1
        if count <= 0:
            return []
        return [
            make_funding_row(inst_id, latest - index * FUNDING_INTERVAL_SECONDS)
            for index in range(min(limit, count))
        ]

    def _require_inst_id(self, inst_id: str) -> dict[str, Any]:
        try:
            return self._by_inst_id[inst_id]
        except KeyError:
            raise OkxApiError(
                UNKNOWN_INST_ID_CODE, f"Instrument ID does not exist:{inst_id}"
            ) from None

    @staticmethod
    def _validate_bar(bar: str) -> None:
        try:
            bar_seconds(bar)
        except ValueError as exc:
            raise OkxApiError(INVALID_PARAMETER_CODE, str(exc)) from None

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if not 1 <= limit <= MAX_CANDLE_LIMIT:
            raise OkxApiError(INVALID_PARAMETER_CODE, f"Parameter limit error:{limit}")
