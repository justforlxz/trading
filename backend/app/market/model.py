"""`candles` / `funding` / `correlation_snapshots` 表：行情、资金费与相关矩阵快照。

`candles` 里一行是一个标的在一个周期、一个开盘时刻上、来自一个数据源的已收盘 K 线；
主键 `(symbol, bar, open_time, source)` 让重复下载变成幂等 upsert，而不是追加副本。

`funding` 里一行是一个永续合约在一个结算时刻上的费率；主键 `(inst_id, funding_time)`
同样让重复采集幂等。两档费率都可为空：上游对「本期没有实现费率」与「费率恰好是 0」
给的是空串 / `"0"` 两种不同事实，落库必须保留这个区别。

时间列存 epoch 秒（整数），不依赖字符串时间格式。价格以文本列存储、用 `Decimal`
收发，避免浮点往返丢掉精度。

日线的 `open_time` 由上游给出（OKX 是 16:00 UTC），本表不改写它；**期望的日界**由
`app/market/session.py` 定：同步窗口与缺口网格都按「该条行情所属市场的交易日
首个 `open_time`」算（美股代理源落在美东 09:30，24/7 市场仍是 UTC+8 零点）。时段
另存一列 `market_session`，读回时随 `Bar` 一起带出。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, Index, Integer, String, TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column

from app.core import Bar, Timeframe, ValidationError
from app.db import Base

if TYPE_CHECKING:  # 只用于类型标注：值对象在 funding 模块，运行期不互相 import。
    from app.market.funding import FundingPoint

_PRICE = String(32)


class DecimalText(TypeDecorator[Decimal]):
    """`Decimal` ↔ 文本列：全仓只有一套十进制精度约定，转字符串才能原样往返。"""

    impl = _PRICE
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Any) -> str | None:
        return None if value is None else format(value, "f")

    def process_result_value(self, value: str | None, dialect: Any) -> Decimal | None:
        return None if value is None else Decimal(value)


def to_epoch(moment: datetime) -> int:
    """带时区的时刻 → epoch 秒；精确到秒，不带小数。"""

    if moment.tzinfo is None:
        raise ValidationError("时刻必须带时区")
    seconds = moment.timestamp()
    if seconds != int(seconds):
        raise ValidationError(f"时刻必须精确到秒:{moment.isoformat()}")
    return int(seconds)


def from_epoch(seconds: int) -> datetime:
    """epoch 秒 → UTC 时刻。"""

    return datetime.fromtimestamp(seconds, tz=UTC)


def now_epoch() -> int:
    """当前 UTC 时刻的 epoch 秒；写入时间同样精确到秒。"""

    return int(datetime.now(tz=UTC).timestamp())


class Candle(Base):
    """已收盘的历史 K 线；未收盘的 K 线不入本表。"""

    __tablename__ = "candles"

    symbol: Mapped[str] = mapped_column(String(64), primary_key=True)
    bar: Mapped[str] = mapped_column(String(8), primary_key=True)
    open_time: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    open: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    high: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    low: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    close: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    volume: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    market_session: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    @classmethod
    def from_bar(cls, bar: Bar) -> Candle:
        """端口返回的 `Bar` → 待写入的行。"""

        if not bar.source:
            raise ValidationError("K 线缺少数据来源")
        return cls(
            symbol=bar.inst_id,
            bar=bar.timeframe.value,
            open_time=to_epoch(bar.open_time),
            source=bar.source,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            updated_at=now_epoch(),
            market_session=bar.market_session,
        )

    def to_bar(self) -> Bar:
        """历史行 → `Bar`；表里只有已收盘 K 线，因此 `confirm` 恒为 True。"""

        return Bar(
            inst_id=self.symbol,
            timeframe=Timeframe.parse(self.bar),
            open_time=from_epoch(self.open_time),
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            confirm=True,
            source=self.source,
            market_session=self.market_session,
        )


class Funding(Base):
    """已结算的资金费；未结算的当期费率不入本表。

    `funding_rate` 是结算期的公布费率，`realized_rate` 是实际收取的费率；
    两列都可为空（上游没给），空值不等于 0——结算环节据此判定「缺失」。
    """

    __tablename__ = "funding"

    inst_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    funding_time: Mapped[int] = mapped_column(Integer, primary_key=True)
    funding_rate: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    realized_rate: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)

    @classmethod
    def from_point(cls, point: FundingPoint) -> Funding:
        """费率点 → 待写入的行。"""

        if not point.inst_id:
            raise ValidationError("资金费缺少标的")
        return cls(
            inst_id=point.inst_id,
            funding_time=to_epoch(point.funding_time),
            funding_rate=point.funding_rate,
            realized_rate=point.realized_rate,
            updated_at=now_epoch(),
        )

    def to_point(self) -> FundingPoint:
        """表行 → 费率点；空费率原样保留，不折成 0。"""

        from app.market.funding import FundingPoint  # 运行期按需 import，避免循环依赖

        return FundingPoint(
            inst_id=self.inst_id,
            funding_time=from_epoch(self.funding_time),
            funding_rate=self.funding_rate,
            realized_rate=self.realized_rate,
        )


class CorrelationSnapshot(Base):
    """一组标的在某个时刻、某个窗口上的相关矩阵快照，可按时间回看。

    主键 `(product_key_a, product_key_b, bar, window, as_of)`：同一 `as_of` 重复保存
    只覆盖那一行，不追加副本，因此回看时同一条关系不会出现两份数值。

    标识是**产品键**而不是交易所标识：关系分析看的是产品，同一产品的现货与永续
    不该各算一条边。对角线（产品与自己的相关）同样入库，`samples` 才有「这个标的
    有多少条样本」这一事实。`coefficient` 是无量纲浮点，double precision 往返无损，
    不需要走十进制文本列；无法计算时为空，`samples` 照实记录实际条数。

    时间列沿用 `candles` 的口径：`as_of` 存 epoch 秒（整数）。
    """

    __tablename__ = "correlation_snapshots"
    # 回看按 (bar, window, as_of) 过滤，主键首列是产品键，用不上；单列出来一条索引。
    __table_args__ = (Index("ix_correlation_snapshots_bar_window_as_of", "bar", "window", "as_of"),)

    product_key_a: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_key_b: Mapped[str] = mapped_column(String(32), primary_key=True)
    bar: Mapped[str] = mapped_column(String(8), primary_key=True)
    window: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of: Mapped[int] = mapped_column(Integer, primary_key=True)
    coefficient: Mapped[float | None] = mapped_column(Float, nullable=True)
    samples: Mapped[int] = mapped_column(Integer, nullable=False)
