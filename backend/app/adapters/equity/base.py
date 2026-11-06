"""真实美股行情适配器的公共契约。"""


class EquitySourceUnavailable(Exception):
    """行情源不可用（无 key / 被限流 / 网络失败）：调用方必须落 `MISSING_SOURCE`。"""


class EquitySymbolNotFound(Exception):
    """源确认该符号不存在（区别于临时不可用，不应重试）。"""
