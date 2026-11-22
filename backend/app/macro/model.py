"""`macro_observations` 表：一个序列在一个时刻、一个 provider 上的观测值。

序列自己的名称、单位与来源地址都由 `app/macro/series.py` 与设置里的 provider 配置决定，
不另存一张只写不读的定义表——没有消费方的表会把后来人引到错的入口。

主键 `(series_id, ts, provider)` 让重复抓取变成幂等 upsert：同一个时刻同一个源抓
三次仍然只有一行。`provider` 进主键是有意的——换源后旧源的数据要能区分开，界面也
只显示当前配置 provider 的行。

`ts` 是 UTC epoch 秒整数，与 `candles.open_time` 同一套约定（`to_epoch` 拒绝秒以下
精度）。`trading_day` 冗余存储归属交易日，供利差按结算日配对；`market_session` 与
`is_delayed` 如实记录这条值是什么时段、是否延迟，不用读的时候再猜。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, DecimalText, UtcDateTime

__all__ = ["MacroObservationRow"]


class MacroObservationRow(Base):
    """一个序列在一个时刻、一个 provider 上的值；重复写入只更新，不新增行。"""

    __tablename__ = "macro_observations"
    __table_args__ = (
        # 读路径按「序列 + 来源」取最新一期、按交易日找上一期，两个条件都带上来源。
        Index(
            "ix_macro_observations_series_provider_day",
            "series_id",
            "provider",
            "trading_day",
        ),
    )

    series_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    trading_day: Mapped[date] = mapped_column(Date, nullable=False)
    market_session: Mapped[str] = mapped_column(String(16), nullable=False)
    is_delayed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
