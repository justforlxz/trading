"""故障场景开关：同一条假 OKX 进程按需表现限流、上游故障与慢响应。

限流与上游故障走 HTTP 状态码（与真实上游一致），业务参数错误走
HTTP 200 + 非零 code，两者不能混用。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Scenario:
    """一个可开关的故障形态。"""

    status_code: int
    code: str
    message: str


RATE_LIMITED = Scenario(status_code=429, code="50011", message="Too Many Requests")
UPSTREAM_ERROR = Scenario(status_code=500, code="50001", message="Internal Server Error")

PRESETS: dict[str, Scenario] = {
    "rate_limited": RATE_LIMITED,
    "upstream_error": UPSTREAM_ERROR,
}


class Scenarios:
    """运行期可变的开关：不重启进程就能切换故障形态。"""

    def __init__(self, *, scenario: Scenario | None = None, delay_seconds: float = 0.0) -> None:
        self._scenario = scenario
        self._delay_seconds = delay_seconds

    @property
    def scenario(self) -> Scenario | None:
        return self._scenario

    @property
    def delay_seconds(self) -> float:
        return self._delay_seconds

    def activate(self, name: str) -> None:
        """打开一个预设故障：`rate_limited` 或 `upstream_error`。"""

        try:
            self._scenario = PRESETS[name]
        except KeyError:
            raise ValueError(f"未知场景:{name!r}, 可选 {sorted(PRESETS)}") from None

    def slow(self, seconds: float) -> None:
        """让每个响应先等待若干秒，用于超时与慢上游用例。"""

        if seconds < 0:
            raise ValueError("延迟必须非负")
        self._delay_seconds = seconds

    def reset(self) -> None:
        """恢复健康应答。"""

        self._scenario = None
        self._delay_seconds = 0.0
