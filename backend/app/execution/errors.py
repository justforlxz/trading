"""执行域独有的错误类型。

跨模块错误体系在 `app/core`，这里只补一个执行域真需要的子类：**模拟账户的拒绝**。

模拟盘没有上游返回码，「可卖持仓不足」这类拒绝只能由本地账本判定。与交易所拒单
（`core.ExecutionRejected`）分开，上层才能区分「真实交易所拒了这张单」与「模拟账户
账本上根本没有这么多持仓」——两者的排查方向和恢复动作不同。

订单状态机的非法转移不是业务失败，按 `core.ValidationError` 抛，不在这里另立类型。
"""

from __future__ import annotations

from app.core import ExecutionRejected

__all__ = ["PaperRejected"]


class PaperRejected(ExecutionRejected):
    """模拟账户拒绝了一笔下单：可减持仓不足（卖出超过持有数量）。

    与真实拒单同样意味着「这张单不会成交」，因此继承 `ExecutionRejected`：调用方
    按这一层捕获即可把订单收敛到 `failed`，需要排障时再区分具体子类。
    """
