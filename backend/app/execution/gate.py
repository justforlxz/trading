"""真实交易门禁（纯决策函数）。

三个独立开关缺一不可，任何一项不满足都拒绝真实下单（fail-closed）：

1. `REAL_TRADING_ENABLED` 显式打开（缺省 false）。
2. OKX 私有接口凭据齐全。
3. 目标策略出现在 `EXECUTION_REAL_STRATEGY_IDS` 里（逐策略放行）。

此外存在未处理的对待差异时，真实下单同样被拒绝——差异未查清就继续交易，
等于在错误的持仓认知上下单。
"""

from dataclasses import dataclass

MODE_PAPER = "paper"
MODE_REAL = "real"

CODE_REAL_DISABLED = "real_trading_disabled"
CODE_CREDENTIALS_MISSING = "execution_credentials_missing"
CODE_STRATEGY_NOT_AUTHORIZED = "execution_strategy_not_authorized"
CODE_RECONCILE_PENDING = "execution_reconcile_pending"


@dataclass(frozen=True, slots=True)
class GateDecision:
    allowed: bool
    mode: str
    code: str | None = None
    message: str = ""

    @property
    def rejected(self) -> bool:
        return not self.allowed


def decide_mode(*, real_trading_enabled: bool) -> str:
    """未显式打开真实开关时永远处于 paper 模式。"""

    return MODE_REAL if real_trading_enabled else MODE_PAPER


def parse_strategy_ids(raw: str | None) -> frozenset[int]:
    """解析逗号分隔的策略 id；非法片段直接忽略，不放行任何策略。"""

    if not raw:
        return frozenset()
    ids: set[int] = set()
    for part in raw.split(","):
        text = part.strip()
        if not text:
            continue
        try:
            value = int(text)
        except ValueError:
            continue
        if value > 0:
            ids.add(value)
    return frozenset(ids)


def credentials_configured(*, api_key: str, api_secret: str, passphrase: str) -> bool:
    return bool(api_key and api_secret and passphrase)


def check_submit(
    *,
    requested_mode: str,
    real_trading_enabled: bool,
    credentials_ready: bool,
    strategy_id: int | None,
    authorized_strategy_ids: frozenset[int],
    open_diffs: int,
) -> GateDecision:
    """决定一笔下单请求的准入结论。paper 模式不看实盘开关、凭据与授权。"""

    if requested_mode == MODE_PAPER:
        return GateDecision(allowed=True, mode=MODE_PAPER)

    if not real_trading_enabled:
        return GateDecision(
            allowed=False,
            mode=MODE_REAL,
            code=CODE_REAL_DISABLED,
            message="真实交易开关未打开 (REAL_TRADING_ENABLED 缺省为 false)",
        )
    if not credentials_ready:
        return GateDecision(
            allowed=False,
            mode=MODE_REAL,
            code=CODE_CREDENTIALS_MISSING,
            message="未配置 OKX API 凭据, 拒绝真实下单",
        )
    if strategy_id is None or strategy_id not in authorized_strategy_ids:
        return GateDecision(
            allowed=False,
            mode=MODE_REAL,
            code=CODE_STRATEGY_NOT_AUTHORIZED,
            message="该策略未获实盘授权",
        )
    if open_diffs > 0:
        return GateDecision(
            allowed=False,
            mode=MODE_REAL,
            code=CODE_RECONCILE_PENDING,
            message="存在未处理的对账差异, 拒绝真实下单",
        )
    return GateDecision(allowed=True, mode=MODE_REAL)


__all__ = [
    "CODE_CREDENTIALS_MISSING",
    "CODE_REAL_DISABLED",
    "CODE_RECONCILE_PENDING",
    "CODE_STRATEGY_NOT_AUTHORIZED",
    "MODE_PAPER",
    "MODE_REAL",
    "GateDecision",
    "check_submit",
    "credentials_configured",
    "decide_mode",
    "parse_strategy_ids",
]
