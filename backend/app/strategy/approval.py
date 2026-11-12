"""策略生命周期的审批状态机：合法转移表与唯一推进入口。

八阶段的取值与顺序见 `docs/prd/v2.md` §三.5 与 `docs/prd/decisions.md` D7；本模块不另起
一套名字，直接沿用契约里的 `StrategyStatus` 取值。

三件事各自只有一处实现：

1. **阶段取值** —— `LIFECYCLE_STAGES` 按决策文档的顺序列出八个阶段，驳回分支
   `rejected` 单独列出：它不是第九个阶段，而是人工审核或回测没有通过时的旁路。
2. **合法转移** —— `TRANSITIONS` 是唯一真源。不在表里的转移一律拒绝并抛
   `ValidationError`，因此「从已回测直接跳到已获实盘授权」这类跳步无法靠调用方自觉
   避免，写错就是 400。
3. **推进** —— `advance` 校验转移是否合法、按目标阶段补齐必填依据，然后在一个事务里
   改实例阶段并写一条审批记录。阶段只有这一个写入口：通用的实例更新端点不接收阶段
   字段（见 `StrategyInstanceUpdateRequest`）。

`validated` 是唯一带前置条件的阶段：它必须由「回测结果满足实例配置的验证门槛」驱动
进入。达标依据由 `ValidationReport` 携带——报告里有该实例配置的门槛（指标名、下限或
上限）与这次回测实测的指标值，`advance` 逐项比对；没有报告、报告不达标、门槛为空时都
抛 `ValidationError`，不存在「先改阶段再补报告」的顺序，也没有可以绕过验证的旁路。

门槛目前不落库：本节点只给实例表加了生命周期相关的五个列，配置验证门槛的界面与存储
还没有归属节点。因此报告里的门槛由调用方按实例配置传入，状态机只负责「不达标不放行」
这件事本身。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from uuid import uuid4

from sqlalchemy import func, select

from app.core import Conflict, InvariantViolation, ValidationError
from app.db import session_scope
from app.strategy.model import StrategyApprovalRow, StrategyInstanceRow
from app.strategy.service import DEFAULT_STATUS, InstanceRecord, get_instance

__all__ = [
    "DRAFT",
    "LIFECYCLE_STAGES",
    "REJECTED",
    "TRANSITIONS",
    "ApprovalTransition",
    "ValidationGate",
    "ValidationReport",
    "advance",
    "check_transition",
    "latest_transition",
    "list_transitions",
]

# 八个阶段的取值顺序与 `docs/prd/decisions.md` D7 逐字一致：机会发现 → 策略生成 →
# 人工审核 → 历史回测 → 量化验证 → 模拟交易 → 实盘授权 → 实盘运行。
LIFECYCLE_STAGES: tuple[str, ...] = (
    "opportunity_discovery",
    "strategy_generation",
    "pending_review",
    "backtested",
    "validated",
    "paper_trading",
    "live_authorized",
    "live_running",
)

# 新建实例落地的阶段，也是驳回后唯一能回到的阶段。
DRAFT = DEFAULT_STATUS

# 驳回分支：审核没通过、或回测/验证的结论不达标时落在这里，之后只能回到草稿重来。
REJECTED = "rejected"

# 合法转移表：键是当前阶段，值是允许进入的下一阶段。表里没有的一律拒绝。
#
# 两点值得说明：
# - `backtested` 只放开 `validated` 与 `rejected`，所以「已回测 → 已获实盘授权」天然
#   被挡住，跳过量化验证的路径不存在。
# - `rejected` 只放开 `strategy_generation`：驳回不是暂停，改完必须重新走审核。
TRANSITIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "opportunity_discovery": frozenset({DRAFT}),
        DRAFT: frozenset({"pending_review"}),
        "pending_review": frozenset({"backtested", REJECTED}),
        "backtested": frozenset({"validated", REJECTED}),
        "validated": frozenset({"paper_trading"}),
        "paper_trading": frozenset({"live_authorized"}),
        "live_authorized": frozenset({"live_running"}),
        "live_running": frozenset(),
        REJECTED: frozenset({DRAFT}),
    }
)


@dataclass(frozen=True, slots=True)
class ValidationGate:
    """一项验证门槛：看哪个指标、允许的下限或上限。

    下限与上限至少要给出一个：两个都不给的门槛既拦不住任何结果，也没说明「达标」是
    什么意思。两边都给时必须下限不大于上限，否则这项门槛永远不可能被满足。
    """

    metric: str
    minimum: Decimal | None = None
    maximum: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise ValidationError("验证门槛必须指定指标名")
        if self.minimum is None and self.maximum is None:
            raise ValidationError(f"验证门槛 {self.metric!r} 至少要给出下限或上限")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValidationError(
                f"验证门槛 {self.metric!r} 的下限 {self.minimum} 大于上限 {self.maximum}"
            )

    def unmet(self, value: Decimal) -> str | None:
        """这项门槛对给定指标值是否不达标；达标返回 `None`。"""

        if self.minimum is not None and value < self.minimum:
            return f"{self.metric}={value} 低于下限 {self.minimum}"
        if self.maximum is not None and value > self.maximum:
            return f"{self.metric}={value} 高于上限 {self.maximum}"
        return None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """一份量化验证报告：实例配置的验证门槛 + 这次回测实测的指标值。

    门槛与指标放在同一份报告里，是因为判定的两份输入必须来自同一时刻：只要其中一份
    能被单独改掉，「不达标也能放行」就重新成立。`failures` 给出逐项的人可读说明，
    `passed` 只是它的反义——调用方不需要自己再算一遍。
    """

    report_id: str
    gates: tuple[ValidationGate, ...]
    metrics: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        identifier = self.report_id.strip() if isinstance(self.report_id, str) else ""
        if not identifier:
            raise ValidationError("验证报告必须带编号")
        if len(identifier) > 64:
            raise ValidationError(f"验证报告编号最长 64 个字符, 实际 {len(identifier)}")
        object.__setattr__(self, "report_id", identifier)
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))

    @property
    def failures(self) -> tuple[str, ...]:
        """未达标项的人可读说明；为空表示这份报告达标。"""

        if not self.gates:
            return ("没有配置验证门槛, 无法判定是否达标",)
        problems: list[str] = []
        for gate in self.gates:
            value = self.metrics.get(gate.metric)
            if value is None:
                problems.append(f"报告缺少指标 {gate.metric}")
                continue
            unmet = gate.unmet(value)
            if unmet is not None:
                problems.append(unmet)
        return tuple(problems)

    @property
    def passed(self) -> bool:
        """逐项门槛全部满足才算达标；缺指标与门槛为空都算不达标。"""

        return not self.failures


@dataclass(frozen=True, slots=True)
class ApprovalTransition:
    """一次阶段推进的记录：谁、在什么时刻、把哪个实例从哪个阶段推到哪个阶段。

    `from_status` 为空只在「实例的第一条记录」上出现——那种情况不属于本模块：实例
    创建时直接落在草稿阶段，不写审批记录。
    """

    approval_id: str
    instance_id: str
    from_status: str | None
    to_status: str
    actor: str
    at: datetime
    note: str | None = None
    evidence: str | None = None


def advance(
    instance: InstanceRecord,
    target: str,
    actor: str,
    evidence: ValidationReport | str | None = None,
    *,
    note: str | None = None,
) -> InstanceRecord:
    """把实例从当前阶段推进到 `target`，写一条审批记录，返回推进后的实例。

    `instance` 只回答两件事：推进哪一个实例，以及调用方认为它现在在哪个阶段。真正的
    判定以事务里锁住的那一行为准：行上的阶段与入参不一致就抛 `Conflict`（409），绝不
    按过期快照写一条转移表之外的结果。因此并发的两次推进里后到的那个会被拒绝，过期的
    `InstanceRecord`（例如库里已经走到 `live_running`、手上还停在 `paper_trading`）也
    不会被当成合法起点——这正是「阶段不可绕过」的一半，另一半是不在转移表里的目标阶段
    直接抛 `ValidationError`。

    `evidence` 对进入 `validated` 是必填的达标报告；其余阶段可以给一个依据引用
    （例如审批单编号），也可以不给。进入不同阶段时实例上记录的事实不同：

    - `backtested`：记下审核通过的人与时刻（`approved_by` / `approved_at`）；
    - `validated`：记下达标报告的编号（`validation_report_id`）；
    - `live_authorized`：记下授权时刻（`live_authorized_at`），不打开实盘开关；
    - `rejected`：驳回使之前的审核与验证结论失效，这几个列一并清空。

    入参不合法、转移不在表里、验证不达标抛 `ValidationError`（400）；实例已被删除或
    阶段已被别的请求推进抛 `Conflict`（409）。调用方不需要也不应该用 `try/except` 把
    状态错误吞掉再改一个阶段。
    """

    current = instance.lifecycle_status
    check_transition(current, target)
    report = _require_report(target, evidence)
    who = _require_actor(actor)
    # 先校验完所有入参再开事务：长度不对的依据不值得占住一行锁。
    note_text = _require_note(note)
    evidence_text = _evidence_text(report, evidence)
    moment = _now()
    with session_scope() as session:
        row = session.get(StrategyInstanceRow, instance.instance_id, with_for_update=True)
        if row is None:
            raise Conflict(f"策略实例 {instance.instance_id} 已被删除, 不能推进阶段")
        previous = row.lifecycle_status
        if previous != current:
            raise Conflict(
                f"策略实例 {instance.instance_id} 的阶段已是 {previous}, "
                f"不再是从 {current} 出发; 请重新读取该实例后再提交"
            )
        row.lifecycle_status = target
        row.updated_at = _epoch(moment)
        _record_facts(row, target, who, report, moment)
        session.add(
            StrategyApprovalRow(
                approval_id="apr_" + uuid4().hex[:24],
                instance_id=instance.instance_id,
                from_status=previous,
                to_status=target,
                actor=who,
                at=_epoch(moment),
                note=note_text,
                evidence=evidence_text,
            )
        )

    advanced = get_instance(instance.instance_id)
    if advanced is None:  # 同一事务里刚写过这一行, 读不到属于「不该发生」
        raise InvariantViolation(f"策略实例 {instance.instance_id} 推进后读不到")
    return advanced


def list_transitions(*, limit: int = 200) -> tuple[tuple[ApprovalTransition, ...], int]:
    """按写入顺序倒序列出审批记录，返回（本页记录，全部条数）。

    记录是历史事实：实例被删掉时随实例级联删除，除此之外只增不改。顺序取写入顺序
    （`seq` 倒序），同一秒内连续推进的先后因此仍然确定。
    """

    if limit < 1:
        raise ValidationError(f"条数上限必须是正整数:{limit}")
    statement = select(StrategyApprovalRow).order_by(StrategyApprovalRow.seq.desc()).limit(limit)
    with session_scope() as session:
        rows = list(session.scalars(statement))
        total = session.scalar(select(func.count()).select_from(StrategyApprovalRow))
    return tuple(_transition(record) for record in rows), total or 0


def check_transition(current: str, target: str) -> None:
    """判定一次转移是否合法：纯函数，不碰库；不合法抛 `ValidationError`。

    单独拿出来是因为「哪些转移合法」是一份可以脱离实例与数据库验算的规则：拒绝跳步、
    拒绝从驳回直接进实盘，都是这张表的事，不需要造一条实例行才能验证。
    """

    if target not in LIFECYCLE_STAGES and target != REJECTED:
        known = ", ".join((*LIFECYCLE_STAGES, REJECTED))
        raise ValidationError(f"未知的生命周期阶段 {target!r}; 支持: {known}")
    allowed = TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ValidationError(
            f"不能从 {current} 直接进入 {target}; 允许进入:{_allowed_text(allowed)}"
        )


def _require_report(
    target: str, evidence: ValidationReport | str | None
) -> ValidationReport | None:
    """进入 `validated` 必须附达标报告；其余阶段不接受报告（给了说明调错了阶段）。"""

    if target != "validated":
        if isinstance(evidence, ValidationReport):
            raise ValidationError(f"只有进入 validated 才需要验证报告, 本次目标是 {target}")
        return None
    if not isinstance(evidence, ValidationReport):
        raise ValidationError("进入 validated 必须附上本次回测的验证报告")
    if not evidence.passed:
        raise ValidationError("验证未达标, 不能进入 validated:" + "; ".join(evidence.failures))
    return evidence


def _evidence_text(
    report: ValidationReport | None, evidence: ValidationReport | str | None
) -> str | None:
    """审批记录里存的依据：达标报告存编号，其余存调用方给的引用。

    长度在这里就校验：落库列是 256 个字符，超长留到写库时才炸出来会变成 500，而它其实
    是可修正的入参问题（400）。
    """

    if report is not None:
        return report.report_id
    if not isinstance(evidence, str) or not evidence.strip():
        return None
    reference = evidence.strip()
    if len(reference) > 256:
        raise ValidationError(f"推进依据最长 256 个字符, 实际 {len(reference)}")
    return reference


def _record_facts(
    row: StrategyInstanceRow,
    target: str,
    actor: str,
    report: ValidationReport | None,
    moment: datetime,
) -> None:
    """按目标阶段在实例上补记对应的事实列。"""

    if target == "backtested":
        row.approved_by = actor
        row.approved_at = _epoch(moment)
    elif target == "validated":
        row.validation_report_id = _require_report_id(report)
    elif target == "live_authorized":
        row.live_authorized_at = _epoch(moment)
    elif target == REJECTED:
        # 驳回：上一次的审核与验证结论不再成立，留着会让实例同时呈现「已驳回」与
        # 「某人已批准」两个互相矛盾的事实。历史仍留在审批记录里。
        row.approved_by = None
        row.approved_at = None
        row.validation_report_id = None


def _require_report_id(report: ValidationReport | None) -> str:
    """`validated` 分支到这里时报告一定存在；缺了属于调用顺序写错。"""

    if report is None:
        raise InvariantViolation("进入 validated 时缺少验证报告")
    return report.report_id


def _require_actor(actor: str) -> str:
    """推进人必须能指出是谁：空白名字等于没有留痕。"""

    name = actor.strip() if isinstance(actor, str) else ""
    if not name:
        raise ValidationError("阶段推进必须记录推进人")
    if len(name) > 128:
        raise ValidationError(f"推进人最长 128 个字符, 实际 {len(name)}")
    return name


def _require_note(note: str | None) -> str | None:
    """备注可空；给了就不能超过列宽。"""

    if note is None:
        return None
    text = note.strip()
    if not text:
        return None
    if len(text) > 512:
        raise ValidationError(f"备注最长 512 个字符, 实际 {len(text)}")
    return text


def _allowed_text(allowed: Sequence[str] | frozenset[str]) -> str:
    """把允许的下一阶段拼成一句话；没有可去的地方时明说。"""

    names = sorted(allowed)
    return ", ".join(names) if names else "无"


def latest_transition(instance_id: str) -> ApprovalTransition | None:
    """该实例最后一条审批记录；没有记录返回 `None`。

    端点刚推进完要回一条记录，而推进的返回值是实例本身（阶段推进的语义是「实例变了」），
    因此按写入顺序取最新一条，不靠时间戳猜。
    """

    statement = (
        select(StrategyApprovalRow)
        .where(StrategyApprovalRow.instance_id == instance_id)
        .order_by(StrategyApprovalRow.seq.desc())
        .limit(1)
    )
    with session_scope() as session:
        row = session.scalars(statement).first()
    return None if row is None else _transition(row)


def _transition(row: StrategyApprovalRow) -> ApprovalTransition:
    """库里的审批行 → 域记录。"""

    return ApprovalTransition(
        approval_id=row.approval_id,
        instance_id=row.instance_id,
        from_status=row.from_status,
        to_status=row.to_status,
        actor=row.actor,
        at=_from_epoch(row.at),
        note=row.note,
        evidence=row.evidence,
    )


def _now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


def _epoch(value: datetime) -> int:
    return int(value.astimezone(UTC).replace(microsecond=0).timestamp())


def _from_epoch(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)
