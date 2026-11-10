"""建库入口：执行版本化迁移（Alembic），不再 `create_all`。

表结构只有一条产生路径——迁移脚本；`init_db()` 把库推进到最新版本，进程启动
与 `make migrate` 走的是同一条命令，不会出现「代码里的表」和「库里的表」不一致。
"""

from alembic import command
from alembic.config import Config

from app.config import BACKEND_DIR

# 迁移配置固定在包目录旁：进程 cwd 是 backend/ 还是仓库根都不影响定位。
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def alembic_config() -> Config:
    """迁移配置；脚本位置与 sys.path 由 ini 里的 `%(here)s` 解析，与 cwd 无关。"""

    return Config(str(ALEMBIC_INI))


def init_db() -> None:
    """把库结构推进到最新版本；已是最新时为空操作（幂等，可重复调用）。"""

    command.upgrade(alembic_config(), "head")
