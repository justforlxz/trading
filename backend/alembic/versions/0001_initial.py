"""空基线迁移：只建立 `alembic_version`，不创建任何业务表。

S3 起每个 schema 的建表迁移都 `down_revision` 指向本版本，保证「容器启动即
`alembic upgrade head`」这条路径从第一天就可用。

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-06
"""

from collections.abc import Sequence

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """S2 无表定义；本迁移只作为版本链起点。"""


def downgrade() -> None:
    """基线回滚为空操作。"""
