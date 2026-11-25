"""`candles` 的 `(symbol, source, open_time, updated_at)` 索引。

首页一次请求里有两处按 `(symbol, source)` 取「每个标的每个来源最近一根 K 线」：

- `app.market.sync.latest_candles_by_source` 用 `DISTINCT ON (symbol, source)` 排序；
- 每条 `LATERAL` 尾巴读取 `(symbol, bar, open_time, source)` 主键的倒序等值前缀。

改动前只有主键 `(symbol, bar, open_time, source)`：`source` 排在 `bar` 与 `open_time`
之后，`(symbol, source)` 的等值前缀取不到，`DISTINCT ON` 那条只能顺序扫整张表再排序
（实测 18762 行、`Seq Scan`、46.5ms）。新索引把 `(symbol, source)` 提到最前，
`open_time DESC` 紧随其后，`DISTINCT ON` 变成 `Bitmap Index Scan` + 排序，
实测 4.5ms（`EXPLAIN (ANALYZE, BUFFERS)` 见 PR 描述）。

只加一条读侧索引，不改表结构与列定义；`downgrade` 直接删掉。

迁移脚本不导入应用代码。

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_candles_symbol_source_open_time"


def upgrade() -> None:
    # 列顺序与查询的 `ORDER BY symbol, source, open_time DESC, updated_at DESC` 一致：
    # `DISTINCT ON` 只要拿到每组的第一行，索引顺序对上就能在组边界上停下。
    op.create_index(
        INDEX_NAME,
        "candles",
        ["symbol", "source", "open_time", "updated_at"],
        unique=False,
        postgresql_ops={"open_time": "DESC", "updated_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="candles")
