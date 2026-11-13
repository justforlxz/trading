"""浏览器实时推送：订阅管理、行情合并、账户与持仓快照分发。

门面即出口：跨包只允许 `from app.stream import ...`。
"""

from app.stream.hub import StreamHub

__all__ = ["StreamHub"]
