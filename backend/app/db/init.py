"""建库建表：v2 用 `Base.metadata.create_all` 落 schema，不引入迁移工具。

单进程 + 单文件库 + 空壳阶段没有历史数据，`create_all` 的「不存在才建」语义
足够可靠；出现第一次需要改列的变更时再引入版本化迁移。
"""

from app.config import get_settings
from app.db.base import Base
from app.db.engine import get_engine


def init_db() -> None:
    """创建库文件所在目录与全部缺失的表（幂等，可重复调用）。"""

    get_settings().database_path.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=get_engine())
