"""`backtest_runs` 补三列：标的身份与完整请求。

一次回测记录的是「某个策略实例在某个标的上的一次运行」，但 0007 建表时只存了策略身份，
没存标的身份：结果列表与排行榜按标的排一行时无从取出是哪只标的。`request_json` 补的是
详情接口要回放的完整输入——参数表里只有 `params_json` / `costs_json`，`targets`、
`position_size`、`max_position_pct`、`quote_currency`、`funding_enabled` 都丢了。

0010 之前的行没有标的与请求可填，也无法从别的列还原：一次运行只存了策略身份，没有
标的，`request_json` 要的 `targets`、`position_size` 等参数同样缺失。这类行无法投影
成现在的契约，留在库里会让列表与详情把空值送进响应模型。按项目「删除即删除，不留
兼容分支」的口径，升级时直接删除这些无法表示的历史行；子表按外键级联删除。

迁移脚本不导入应用代码。

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 0010 之前的记录无法补出标的与完整请求，保留只会变成读不出来的坏数据。
    op.execute("DELETE FROM backtest_runs")
    op.add_column(
        "backtest_runs",
        sa.Column("inst_id", sa.String(length=32), nullable=False),
    )
    op.add_column(
        "backtest_runs",
        sa.Column("inst_type", sa.String(length=8), nullable=False),
    )
    op.add_column(
        "backtest_runs",
        sa.Column("request_json", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_backtest_runs_inst_id",
        "backtest_runs",
        ["inst_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_inst_id", table_name="backtest_runs")
    op.drop_column("backtest_runs", "request_json")
    op.drop_column("backtest_runs", "inst_type")
    op.drop_column("backtest_runs", "inst_id")
