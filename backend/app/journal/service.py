"""交易历史的读取编排：从既有表读出策略与回测，再和执行快照合成视图。

这里是 journal 唯一接触数据库的地方，而且只有读取：不建表、不写行、不触发回测。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import select

from app.backtest import BacktestRunRow
from app.db import session_scope
from app.journal.aggregate import build_journal
from app.journal.model import ExecutionSnapshot, JournalView
from app.strategy import InstanceRecord, get_instance, list_instances

__all__ = ["latest_expectations", "load_journal"]


def latest_expectations(
    instances: Iterable[InstanceRecord],
) -> dict[str, tuple[Decimal | None, str]]:
    """每个实例最近一次可用回测的预期收益与来源。

    回测按标的逐条落库，一次运行只覆盖一个标的。这里只认「标的属于该实例当前标的
    集合、版本与实例当前版本一致」的运行：多腿策略不会拿另一条腿的结果冒充预期，
    实例改过标的或版本之后也不会继续引用旧配置的结果。收益取指标里的 `total_return`
    （比率，0.12 表示 12%），来源带上运行标识、标的与版本，读的人可以回到那次运行核对。
    """

    wanted = {record.instance_id: record for record in instances if record.instance_id}
    if not wanted:
        return {}
    statement = (
        select(BacktestRunRow)
        .where(BacktestRunRow.strategy_instance_id.in_(tuple(wanted)))
        .order_by(
            BacktestRunRow.strategy_instance_id,
            BacktestRunRow.created_at.desc(),
            BacktestRunRow.run_id,
        )
    )
    found: dict[str, tuple[Decimal | None, str]] = {}
    with session_scope() as session:
        for row in session.scalars(statement):
            if row.strategy_instance_id in found:
                continue
            record = wanted[row.strategy_instance_id]
            if row.inst_id not in record.inst_ids:
                continue
            if row.strategy_version != record.strategy_version:
                continue
            metrics = json.loads(row.metrics_json)
            raw = metrics.get("total_return")
            value = None if raw is None else Decimal(str(raw))
            found[row.strategy_instance_id] = (
                value,
                f"backtest:{row.run_id}:{row.inst_id}:{row.strategy_version}:metrics.total_return",
            )
    return found


def load_journal(
    *,
    snapshot: ExecutionSnapshot | None = None,
    instance_id: str | None = None,
    limit: int = 100,
) -> JournalView | None:
    """读取交易历史；指定实例不存在时返回 `None`，由接口层翻成 404。"""

    if instance_id is not None:
        record = get_instance(instance_id)
        if record is None:
            return None
        instances = (record,)
    else:
        instances, _ = list_instances(limit=limit)
    expectations = latest_expectations(instances)
    return build_journal(instances, expectations, snapshot or ExecutionSnapshot())
