"""真实美股行情适配器：可切换来源，缺失时显式报 `MISSING_SOURCE`，不伪造。"""

from app.adapters.equity.registry import build_equity_source

__all__ = ["build_equity_source"]
