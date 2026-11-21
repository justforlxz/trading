"""watchlist 域测试装配：表元数据注册。

库与表结构都由根 `conftest.py` 准备好（每个用例独立库，从已迁移的模板库克隆），
这里没有需要额外做的装配。
"""

# 导入即注册表元数据（与 `app.main` 的装配路径一致）。
from app.instrument import Instrument  # noqa: F401
from app.market import Candle  # noqa: F401
from app.watchlist import WatchlistItemRow  # noqa: F401
