"""策略审批状态机：转移表全组合、达标报告门禁、每个阶段记下的推进事实。

两部分各管一件事：

- 转移表是脱离数据库就能验算的规则，因此全组合（9 个取值两两组合共 81 组）走纯函数的
  `check_transition`；期望的允许集在测试里逐条写死，不从 `TRANSITIONS` 反推——否则实现
  改错、测试跟着改对，门禁就不再拦人。
- 写库那一半只保留必要的几条：达标报告门禁、跳步与驳回出口、每条转移写一条记录、
  实例上的凭据列。这几条要真落库才能验证，因此请求根 `conftest.py` 的临时 schema。

纯函数用例不请求库夹具：每请求一次就要把八个迁移重跑一遍。
"""

from __future__ import annotations

from decimal import Decimal
from typing import get_args

import pytest
from sqlalchemy import select

from app.api.schemas.common import StrategyStatus
from app.core import Conflict, ValidationError
from app.db import init_db, session_scope
from app.instrument import sync_instruments
from app.strategy import (
    DRAFT,
    LIFECYCLE_STAGES,
    REJECTED,
    TRANSITIONS,
    InstanceRecord,
    StrategyApprovalRow,
    StrategyInstanceRow,
    ValidationGate,
    ValidationReport,
    advance,
    check_transition,
    create_instance,
    delete_instance,
    get_instance,
    list_transitions,
)
from tests.factories.instruments import make_ref

#: 八个阶段加上驳回分支：转移表涉及的全部取值。
ALL_STAGES: tuple[str, ...] = (*LIFECYCLE_STAGES, REJECTED)

#: 转移表要覆盖的全部 (起点, 目标) 组合。
ALL_PAIRS: tuple[tuple[str, str], ...] = tuple(
    (source, target) for source in ALL_STAGES for target in ALL_STAGES
)

#: 允许的转移，逐条按决策文档写出（`docs/prd/decisions.md` D7 的八阶段 + 驳回分支）。
#:
#: 这里刻意不使用 `TRANSITIONS` 反向生成：这份集合就是规格，实现偏离它时测试要变红。
ALLOWED_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("opportunity_discovery", DRAFT),
        (DRAFT, "pending_review"),
        ("pending_review", "backtested"),
        ("pending_review", REJECTED),
        ("backtested", "validated"),
        ("backtested", REJECTED),
        ("validated", "paper_trading"),
        ("paper_trading", "live_authorized"),
        ("live_authorized", "live_running"),
        (REJECTED, DRAFT),
    }
)

ACTOR = "lxz"

#: 一份达标报告：回撤 0.1 不超过上限 0.2，夏普 1.5 不低于下限 1.0。
GATES: tuple[ValidationGate, ...] = (
    ValidationGate("max_drawdown", maximum=Decimal("0.2")),
    ValidationGate("sharpe", minimum=Decimal("1")),
)
METRICS: dict[str, Decimal] = {
    "max_drawdown": Decimal("0.1"),
    "sharpe": Decimal("1.5"),
}


@pytest.fixture()
def approval_schema() -> None:
    """执行迁移建表；schema 由根 conftest 隔离，用完整块删掉。"""

    init_db()


@pytest.fixture()
def instance(approval_schema: None) -> InstanceRecord:
    """一条草稿阶段的实例：两支加密现货，模板参数取默认值。

    实例走真实写入路径（模板投影 + 标的解析 + 参数校验），不手写行——状态机要拦的正是
    「绕过这些校验直接把阶段改掉」，夹具自己不该绕过去。
    """

    sync_instruments(
        [
            make_ref(inst_id="BTC-USDT", base_ccy="BTC", inst_category="1"),
            make_ref(inst_id="ETH-USDT", base_ccy="ETH", inst_category="1"),
        ]
    )
    return create_instance(
        strategy_id="relative_value",
        name="BTC/ETH 配对",
        bar="1d",
        inst_ids=["BTC-USDT", "ETH-USDT"],
    )


def passing_report(report_id: str = "br_20261112") -> ValidationReport:
    """一份达标报告；门槛与指标就是上面那两组常量。"""

    return ValidationReport(report_id=report_id, gates=GATES, metrics=METRICS)


def force_stage(instance_id: str, stage: str) -> None:
    """把实例摆到某个阶段，作为用例的起点。

    这是夹具在造状态，不是被测代码的写路径：推进只能在 `advance` 里发生，而要覆盖
    「从任意阶段出发」只能先把行摆到那个阶段。
    """

    with session_scope() as session:
        row = session.get(StrategyInstanceRow, instance_id)
        assert row is not None
        row.lifecycle_status = stage


def read_instance(instance_id: str) -> InstanceRecord:
    record = get_instance(instance_id)
    assert record is not None
    return record


def approval_rows(instance_id: str) -> list[StrategyApprovalRow]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(StrategyApprovalRow).where(StrategyApprovalRow.instance_id == instance_id)
            )
        )


def test_transition_table_matches_the_specification() -> None:
    """转移表的每一条都与规格一致：不多放开一条，也不少一条。"""

    expected: dict[str, frozenset[str]] = {stage: frozenset() for stage in ALL_STAGES}
    for source, target in ALLOWED_PAIRS:
        expected[source] |= {target}

    assert dict(TRANSITIONS) == expected
    assert set(TRANSITIONS) == set(ALL_STAGES)


@pytest.mark.parametrize(("source", "target"), ALL_PAIRS)
def test_only_listed_transitions_are_accepted(source: str, target: str) -> None:
    """81 组组合：规格里允许的放行，其余一律抛 `ValidationError`。"""

    if (source, target) in ALLOWED_PAIRS:
        check_transition(source, target)
    else:
        with pytest.raises(ValidationError):
            check_transition(source, target)


def test_stages_match_the_contract_enum() -> None:
    """阶段取值与契约里冻结的枚举逐字一致：两侧各写一套名字迟早会对不上。

    `app.strategy` 不能反向依赖 `app.api`（装配层），因此这条一致性由测试把关，而不是
    在域里导入契约模型。
    """

    assert set(get_args(StrategyStatus)) == set(ALL_STAGES)


def test_unknown_stage_is_rejected() -> None:
    """取值不在决策文档里的一律拒绝，不做「拼写相近就放行」的猜测。"""

    with pytest.raises(ValidationError) as raised:
        check_transition(DRAFT, "approved")

    assert "approved" in str(raised.value)


def test_validated_needs_a_passing_report(instance: InstanceRecord) -> None:
    """没有报告、报告不达标都进不了 `validated`；达标的才能进去。"""

    force_stage(instance.instance_id, "backtested")
    current = read_instance(instance.instance_id)

    with pytest.raises(ValidationError):
        advance(current, "validated", ACTOR)
    with pytest.raises(ValidationError):
        advance(
            current,
            "validated",
            ACTOR,
            ValidationReport(
                report_id="br_failed",
                gates=GATES,
                metrics={"max_drawdown": Decimal("0.1"), "sharpe": Decimal("0.4")},
            ),
        )
    assert read_instance(instance.instance_id).lifecycle_status == "backtested"
    assert approval_rows(instance.instance_id) == []

    advanced = advance(current, "validated", ACTOR, passing_report())
    assert advanced.lifecycle_status == "validated"
    assert advanced.validation_report_id == "br_20261112"

    rows = approval_rows(instance.instance_id)
    assert [(row.from_status, row.to_status) for row in rows] == [("backtested", "validated")]
    assert rows[0].evidence == "br_20261112"


def test_backtested_cannot_jump_to_live_authorization(instance: InstanceRecord) -> None:
    """跳过量化验证的路径不存在：已回测不能直接进实盘授权，且不留任何痕迹。"""

    force_stage(instance.instance_id, "backtested")
    current = read_instance(instance.instance_id)

    with pytest.raises(ValidationError) as raised:
        advance(current, "live_authorized", ACTOR)

    assert "validated" in str(raised.value)
    assert read_instance(instance.instance_id).lifecycle_status == "backtested"
    assert approval_rows(instance.instance_id) == []


def test_rejected_only_returns_to_the_draft(instance: InstanceRecord) -> None:
    """驳回之后只能回到草稿，不能直接进实盘授权。"""

    force_stage(instance.instance_id, "rejected")
    current = read_instance(instance.instance_id)

    with pytest.raises(ValidationError):
        advance(current, "live_authorized", ACTOR)
    assert read_instance(instance.instance_id).lifecycle_status == "rejected"

    assert advance(current, DRAFT, ACTOR).lifecycle_status == DRAFT


def test_every_transition_writes_a_record(instance: InstanceRecord) -> None:
    """整条主链走完写六条记录，每条都带推进人、起止阶段与时刻。"""

    chain = (
        ("pending_review", None),
        ("backtested", None),
        ("validated", passing_report()),
        ("paper_trading", None),
        ("live_authorized", None),
        ("live_running", None),
    )
    for target, evidence in chain:
        advance(read_instance(instance.instance_id), target, ACTOR, evidence)

    rows = approval_rows(instance.instance_id)
    assert len(rows) == len(chain)
    assert {(row.from_status, row.to_status) for row in rows} == {
        (DRAFT, "pending_review"),
        ("pending_review", "backtested"),
        ("backtested", "validated"),
        ("validated", "paper_trading"),
        ("paper_trading", "live_authorized"),
        ("live_authorized", "live_running"),
    }
    assert {row.actor for row in rows} == {ACTOR}
    assert all(row.at > 0 for row in rows)

    records, total = list_transitions()
    assert total == len(chain)
    assert {record.approval_id for record in records} == {row.approval_id for row in rows}
    assert all(record.actor == ACTOR for record in records)


def test_milestones_are_recorded_on_the_instance(instance: InstanceRecord) -> None:
    """审核、验证、授权各自把凭据记到实例上；驳回使审核凭据失效并清空。"""

    advance(read_instance(instance.instance_id), "pending_review", ACTOR)
    approved = advance(read_instance(instance.instance_id), "backtested", "reviewer")
    assert approved.approved_by == "reviewer"
    assert approved.approved_at is not None

    advance(read_instance(instance.instance_id), "rejected", ACTOR)
    assert read_instance(instance.instance_id).approved_by is None
    assert read_instance(instance.instance_id).approved_at is None

    advance(read_instance(instance.instance_id), DRAFT, ACTOR)
    advance(read_instance(instance.instance_id), "pending_review", ACTOR)
    advance(read_instance(instance.instance_id), "backtested", ACTOR)
    validated = advance(read_instance(instance.instance_id), "validated", ACTOR, passing_report())
    assert validated.validation_report_id == "br_20261112"
    assert validated.live_authorized_at is None

    advance(read_instance(instance.instance_id), "paper_trading", ACTOR)
    authorized = advance(read_instance(instance.instance_id), "live_authorized", ACTOR)
    assert authorized.live_authorized_at is not None


def test_stale_snapshot_cannot_be_the_starting_point(instance: InstanceRecord) -> None:
    """过期快照不能当成起点：判定按库里的阶段，不按调用方手里的旧值。

    构造的是评审给的例子——库里已经走到 `live_running`，手上还停在 `paper_trading`。
    从 `paper_trading` 看 `live_authorized` 是合法目标，所以这条用例唯一能拦住它的地方
    就是把入参与事务内锁住的那一行做比对。
    """

    for target, evidence in (
        ("pending_review", None),
        ("backtested", None),
        ("validated", passing_report()),
        ("paper_trading", None),
    ):
        advance(read_instance(instance.instance_id), target, ACTOR, evidence)
    stale = read_instance(instance.instance_id)
    advance(stale, "live_authorized", ACTOR)
    advance(read_instance(instance.instance_id), "live_running", ACTOR)
    written = len(approval_rows(instance.instance_id))

    with pytest.raises(Conflict):
        advance(stale, "live_authorized", ACTOR)

    assert read_instance(instance.instance_id).lifecycle_status == "live_running"
    assert len(approval_rows(instance.instance_id)) == written


def test_deleted_instance_cannot_be_advanced(instance: InstanceRecord) -> None:
    """实例在推进过程中被删除时回 409，而不是按一个已经不存在的事实写记录。"""

    snapshot = read_instance(instance.instance_id)
    assert delete_instance(instance.instance_id) is True

    with pytest.raises(Conflict):
        advance(snapshot, "pending_review", ACTOR)


def test_overlong_evidence_is_rejected(instance: InstanceRecord) -> None:
    """依据引用超过列宽是可修正的入参问题（400），不能留到写库时变成 500。"""

    with pytest.raises(ValidationError):
        advance(instance, "pending_review", ACTOR, "x" * 300)

    assert approval_rows(instance.instance_id) == []


def test_overlong_report_id_is_rejected() -> None:
    """报告编号落库列是 64 个字符，超长同样在入口处拒绝。"""

    with pytest.raises(ValidationError):
        ValidationReport(report_id="r" * 65, gates=GATES, metrics=METRICS)


def test_actor_is_required(instance: InstanceRecord) -> None:
    """没有推进人的推进等于没有留痕，直接拒绝且不写记录。"""

    with pytest.raises(ValidationError):
        advance(instance, "pending_review", "   ")

    assert approval_rows(instance.instance_id) == []


def test_report_only_belongs_to_the_validated_step(instance: InstanceRecord) -> None:
    """给别的目标阶段附一份验证报告是调错了阶段，不能悄悄忽略。"""

    with pytest.raises(ValidationError):
        advance(instance, "pending_review", ACTOR, passing_report())

    assert approval_rows(instance.instance_id) == []


def test_report_without_gates_does_not_pass() -> None:
    """门槛为空时无法判定，按不达标处理——空门槛不是「全都通过」。"""

    report = ValidationReport(report_id="br_empty", gates=(), metrics=METRICS)
    assert report.passed is False
    assert "验证门槛" in report.failures[0]


def test_report_missing_a_metric_does_not_pass() -> None:
    """报告缺少某个门槛要看的指标时，那一项不能被当成达标。"""

    report = ValidationReport(
        report_id="br_partial",
        gates=GATES,
        metrics={"max_drawdown": Decimal("0.1")},
    )
    assert report.passed is False
    assert "sharpe" in " ".join(report.failures)


def test_gate_needs_a_bound_and_ordered_bounds() -> None:
    """门槛至少要有下限或上限，两边都给时下限不能大于上限。"""

    with pytest.raises(ValidationError):
        ValidationGate("sharpe")
    with pytest.raises(ValidationError):
        ValidationGate("sharpe", minimum=Decimal("2"), maximum=Decimal("1"))
    with pytest.raises(ValidationError):
        ValidationGate("  ", minimum=Decimal("1"))
