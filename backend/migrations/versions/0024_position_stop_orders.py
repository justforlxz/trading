"""交易所持仓快照补两列止损信息。

`stop_px` 与 `stop_status` 由同步流程从 OKX 的策略委托（`orders-algo-pending` 四类
`ordType`）与订单上的 `slTriggerPx` 解析后写入，读侧不再联网。

`stop_status` 是三态而不是「有价位 / 没价位」两态：

- `confirmed`：查到止损触发价，`stop_px` 有值；
- `none`：四类策略委托与订单都问过了，确实没有止损；
- `unavailable`：这次没问成。默认值取它，因为历史行从没查过止损，说成「没有」
  就是在撒谎。

迁移脚本不导入应用代码。

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "exchange_position_snapshots",
        sa.Column("stop_px", sa.Text(), nullable=True),
    )
    op.add_column(
        "exchange_position_snapshots",
        sa.Column(
            "stop_status", sa.String(length=16), nullable=False, server_default="unavailable"
        ),
    )


def downgrade() -> None:
    op.drop_column("exchange_position_snapshots", "stop_status")
    op.drop_column("exchange_position_snapshots", "stop_px")
