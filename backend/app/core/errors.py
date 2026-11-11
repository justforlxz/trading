"""跨模块错误体系。

`core` 冻结的是**可预期失败**：任何模块因业务原因无法完成请求时，只抛这里定义的
类型，调用方按类型分派，不需要猜测被调方抛了什么。

编程错误（内部参数形态不对、不该出现的状态组合）不属于业务失败，继续用
`ValueError` / `TypeError`，由测试兜住——把它们塞进业务异常体系会让「用户传错了」
和「代码写错了」变成同一类，日志里再也分不开。

HTTP 状态码只在 API 边界读取一次（`http_status`），其余层不得自行决定状态码。
"""

from __future__ import annotations

from typing import ClassVar

__all__ = [
    "Conflict",
    "DataUnavailable",
    "ExecutionRejected",
    "InvariantViolation",
    "RiskBlocked",
    "TradingError",
    "UpstreamError",
    "ValidationError",
]


class TradingError(Exception):
    """所有可预期失败的基类。

    子类用 `http_status` 声明边界映射；捕获方先按具体子类分派，兜底再捕获本类。
    """

    http_status: ClassVar[int] = 500


class ValidationError(TradingError):
    """调用方给的参数、配置或名字不合法（请求可以被修正后重试）。"""

    http_status: ClassVar[int] = 400


class UpstreamError(TradingError):
    """外部依赖（交易所、行情源）报错，或返回了无法理解的数据。"""

    http_status: ClassVar[int] = 502


class DataUnavailable(TradingError):
    """数据暂不可用：本地没有、上游休市或还没同步。稍后重试可能成功。"""

    http_status: ClassVar[int] = 503


class Conflict(TradingError):
    """请求与资源当前状态冲突（已停用、状态不允许等）。

    请求本身是合法的，改成别的状态之后才可能成功；因此与参数不合法（400）区分开，
    也不属于风控拒绝（风控拒绝的是交易意图，这里拒绝的是一次操作）。
    """

    http_status: ClassVar[int] = 409


class RiskBlocked(TradingError):
    """风控拒绝了一笔意图。

    `rule` 是拒绝来源（规则名），`detail` 说明触发条件；两者分开是为了让上层
    既能按规则统计拒绝分布，又能原样展示给用户。
    """

    http_status: ClassVar[int] = 409

    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail


class ExecutionRejected(TradingError):
    """交易所明确拒绝了订单（余额不足、标的下架、参数被拒等）。"""

    http_status: ClassVar[int] = 422


class InvariantViolation(TradingError):
    """内部状态违反了约定，属于「不该发生」；需要人工介入而不是重试。"""

    http_status: ClassVar[int] = 500
