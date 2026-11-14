"""v6 用户策略的持久化：策略、不可变版本、版本标的与回测关联。

这一层只回答「用户策略长什么样」。规则如何计算、组合如何生成仍由模板与组件负责；
本模块不碰交易执行，也不改审批状态机。

版本是这里的核心约束：`strategy_versions` 的行创建后不修改，任何规则、参数、周期、
方向、仓位或标的的变化都新建下一版。唯一允许在版本创建后调整的是「当前版本」的
标的集合（`PUT .../versions/{version}/instruments`），因为选择标的属于分析范围而不是
规则内容；旧版本一律拒绝修改，历史回测才能稳定指向当时那一版。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.core import Conflict, InvariantViolation, ValidationError
from app.db import session_scope
from app.instrument import list_instruments
from app.strategy.model import (
    StrategyInstrumentRow,
    StrategyLinkedBacktestRow,
    StrategyVersionRow,
    UserStrategyRow,
)
from app.strategy.rules import (
    DIRECTIONS,
    TIMEFRAMES,
    canonical_json,
    normalize_rule,
    validate_position_sizing,
)

__all__ = [
    "InstrumentStrategyRecord",
    "StrategyRecord",
    "StrategyVersionRecord",
    "create_strategy",
    "create_version",
    "get_user_strategy",
    "get_version",
    "link_backtest",
    "list_strategies_for_instrument",
    "list_user_strategies",
    "list_versions",
    "replace_version_instruments",
    "update_strategy",
]

STATUSES = ("draft", "validated", "enabled", "paused", "archived")
DEFAULT_STATUS = "draft"
MAX_LIMIT = 100

_VERSION_FIELDS = frozenset(
    {
        "timeframe",
        "direction",
        "rule_json",
        "parameters",
        "instrument_ids",
        "cost_model",
        "position_sizing",
        "change_note",
    }
)
_METADATA_FIELDS = frozenset({"name", "category", "description", "status"})

# 这三个字段没有「清空」语义，显式传 null 与省略不同：省略表示沿用当前版本，
# null 说明调用方想写一个空值。按不合法输入拒绝，避免把 None 迭代或当成继承。
_REQUIRED_VERSION_VALUES = frozenset({"rule_json", "parameters", "instrument_ids"})


@dataclass(frozen=True, slots=True)
class StrategyVersionRecord:
    """一个版本的全部可复现输入。"""

    version_id: str
    strategy_id: str
    version: int
    timeframe: str
    direction: str
    rule_json: Mapping[str, Any]
    parameters: Mapping[str, Any]
    position_sizing: Mapping[str, Any] | None
    cost_model: Mapping[str, Any] | None
    change_note: str | None
    instrument_ids: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StrategyRecord:
    """一条用户策略 + 当前版本快照 + 全部版本标识。"""

    id: str
    name: str
    category: str
    description: str | None
    status: str
    current_version_id: str
    current_version: int
    timeframe: str
    direction: str
    rule_json: Mapping[str, Any]
    parameters: Mapping[str, Any]
    position_sizing: Mapping[str, Any] | None
    cost_model: Mapping[str, Any] | None
    instrument_ids: tuple[str, ...]
    version_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class InstrumentStrategyRecord:
    """标的详情页的一条关联策略：策略本身与所有引用该标的的版本。"""

    strategy: StrategyRecord
    version_ids: tuple[str, ...]


def list_user_strategies(
    *,
    status: str | None = None,
    category: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[tuple[StrategyRecord, ...], str | None]:
    """按状态与类别列出用户策略（新到旧），返回（本页记录，下一页游标）。"""

    if limit < 1 or limit > MAX_LIMIT:
        raise ValidationError(f"条数上限必须在 1 到 {MAX_LIMIT} 之间: {limit}")
    conditions = []
    if status is not None:
        _require_status(status)
        conditions.append(UserStrategyRow.status == status)
    if category is not None:
        conditions.append(UserStrategyRow.category == _require_category(category))
    if cursor:
        created_at, strategy_id = _parse_cursor(cursor)
        conditions.append(
            (UserStrategyRow.created_at < created_at)
            | ((UserStrategyRow.created_at == created_at) & (UserStrategyRow.id > strategy_id))
        )

    statement = (
        select(UserStrategyRow)
        .where(*conditions)
        .order_by(UserStrategyRow.created_at.desc(), UserStrategyRow.id)
        .limit(limit + 1)
    )
    with session_scope() as session:
        rows = list(session.scalars(statement))
        page = rows[:limit]
        records = _records(session, page)
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1]
        next_cursor = f"{int(last.created_at.timestamp())}:{last.id}"
    return records, next_cursor


def get_user_strategy(strategy_id: str) -> StrategyRecord | None:
    if not strategy_id:
        raise ValidationError("策略标识不能为空")
    with session_scope() as session:
        row = session.get(UserStrategyRow, strategy_id)
        if row is None:
            return None
        return _records(session, [row])[0]


def create_strategy(
    *,
    name: str,
    category: str,
    description: str | None,
    timeframe: str,
    direction: str,
    rule_json: Mapping[str, Any],
    parameters: Mapping[str, Any] | None,
    instrument_ids: Sequence[str],
    cost_model: Mapping[str, Any] | None,
    position_sizing: Mapping[str, Any] | None,
    change_note: str | None,
) -> StrategyRecord:
    """创建策略与第一个草稿版本。"""

    now = _now()
    instruments = _resolve_instruments(instrument_ids)
    rule, sizing = _prepare_rule(
        rule_json,
        timeframe=timeframe,
        direction=direction,
        position_sizing=position_sizing,
    )
    strategy_row = UserStrategyRow(
        id="st_" + uuid4().hex[:24],
        name=_require_name(name),
        category=_require_category(category),
        description=_require_description(description),
        status=DEFAULT_STATUS,
        created_at=now,
        updated_at=now,
    )
    with session_scope() as session:
        session.add(strategy_row)
        session.flush()
        _insert_version(
            session,
            strategy_row,
            current=None,
            timeframe=timeframe,
            direction=direction,
            rule=rule,
            parameters=parameters,
            sizing=sizing,
            cost_model=cost_model,
            change_note=change_note,
            instruments=instruments,
            now=now,
        )
    record = get_user_strategy(strategy_row.id)
    if record is None:
        raise InvariantViolation("策略创建后读不到")
    return record


def update_strategy(strategy_id: str, changes: Mapping[str, Any]) -> StrategyRecord | None:
    """改元数据，或在提交版本字段时新建下一版。"""

    unknown = sorted(set(changes) - _VERSION_FIELDS - _METADATA_FIELDS)
    if unknown:
        raise ValidationError(f"更新请求含未知字段: {', '.join(unknown)}")
    if not changes:
        raise ValidationError("更新请求至少需要一项字段")

    version_changes = {key: value for key, value in changes.items() if key in _VERSION_FIELDS}
    _reject_null_version_values(version_changes)
    now = _now()
    with session_scope() as session:
        strategy = session.get(UserStrategyRow, strategy_id, with_for_update=True)
        if strategy is None:
            return None
        if "name" in changes:
            strategy.name = _require_name(changes["name"])
        if "category" in changes:
            strategy.category = _require_category(changes["category"])
        if "description" in changes:
            strategy.description = _require_description(changes["description"])
        if "status" in changes:
            strategy.status = _require_status(changes["status"])
        if version_changes:
            current = _current_version(session, strategy_id)
            if current is None:
                raise InvariantViolation(f"策略 {strategy_id} 没有任何版本")
            _insert_version(
                session,
                strategy,
                current=current,
                timeframe=version_changes.get("timeframe"),
                direction=version_changes.get("direction"),
                rule=version_changes.get("rule_json"),
                parameters=version_changes.get("parameters"),
                sizing=version_changes.get("position_sizing", _UNSET),
                cost_model=version_changes.get("cost_model", _UNSET),
                change_note=version_changes.get("change_note"),
                instruments=(
                    _resolve_instruments(version_changes["instrument_ids"])
                    if "instrument_ids" in version_changes
                    else None
                ),
                now=now,
                current_instruments=(
                    None
                    if "instrument_ids" in version_changes
                    else _version_instruments(session, current.id)
                ),
            )
        strategy.updated_at = now
    return get_user_strategy(strategy_id)


def create_version(strategy_id: str, changes: Mapping[str, Any]) -> StrategyRecord | None:
    """为已有策略新建下一个版本；策略不存在返回 `None`。"""

    unknown = sorted(set(changes) - _VERSION_FIELDS)
    if unknown:
        raise ValidationError(f"版本请求含未知字段: {', '.join(unknown)}")
    if not changes:
        raise ValidationError("版本请求至少需要一项字段")
    _reject_null_version_values(changes)

    now = _now()
    with session_scope() as session:
        strategy = session.get(UserStrategyRow, strategy_id, with_for_update=True)
        if strategy is None:
            return None
        current = _current_version(session, strategy_id)
        if current is None:
            raise InvariantViolation(f"策略 {strategy_id} 没有任何版本")
        _insert_version(
            session,
            strategy,
            current=current,
            timeframe=changes.get("timeframe"),
            direction=changes.get("direction"),
            rule=changes.get("rule_json"),
            parameters=changes.get("parameters"),
            sizing=changes.get("position_sizing", _UNSET),
            cost_model=changes.get("cost_model", _UNSET),
            change_note=changes.get("change_note"),
            instruments=(
                _resolve_instruments(changes["instrument_ids"])
                if "instrument_ids" in changes
                else None
            ),
            now=now,
            current_instruments=(
                None if "instrument_ids" in changes else _version_instruments(session, current.id)
            ),
        )
        strategy.updated_at = now
    return get_user_strategy(strategy_id)


def list_versions(strategy_id: str) -> tuple[StrategyVersionRecord, ...] | None:
    with session_scope() as session:
        if session.get(UserStrategyRow, strategy_id) is None:
            return None
        rows = list(
            session.scalars(
                select(StrategyVersionRow)
                .where(StrategyVersionRow.strategy_id == strategy_id)
                .order_by(StrategyVersionRow.version.desc())
            )
        )
        instruments = _instruments_by_version(session, [row.id for row in rows])
    return tuple(_version_record(row, instruments.get(row.id, ())) for row in rows)


def get_version(strategy_id: str, version: int) -> StrategyVersionRecord | None:
    with session_scope() as session:
        row = session.scalar(
            select(StrategyVersionRow).where(
                StrategyVersionRow.strategy_id == strategy_id,
                StrategyVersionRow.version == version,
            )
        )
        if row is None:
            return None
        instruments = _version_instruments(session, row.id)
    return _version_record(row, instruments)


def replace_version_instruments(
    strategy_id: str, version: int, instrument_ids: Sequence[str]
) -> StrategyVersionRecord | None:
    """替换当前版本的标的集合；旧版本拒绝修改（409），整批替换在一个事务里完成。"""

    instruments = _resolve_instruments(instrument_ids)
    now = _now()
    with session_scope() as session:
        strategy = session.get(UserStrategyRow, strategy_id, with_for_update=True)
        if strategy is None:
            return None
        row = session.scalar(
            select(StrategyVersionRow).where(
                StrategyVersionRow.strategy_id == strategy_id,
                StrategyVersionRow.version == version,
            )
        )
        if row is None:
            return None
        current = _current_version(session, strategy_id)
        if current is None or current.id != row.id:
            raise Conflict(f"策略版本 {version} 已不可修改; 请为新版本设置标的")
        session.execute(
            delete(StrategyInstrumentRow).where(StrategyInstrumentRow.strategy_version_id == row.id)
        )
        _insert_instruments(session, row.id, instruments, now)
        strategy.updated_at = now
    return get_version(strategy_id, version)


def list_strategies_for_instrument(inst_id: str) -> tuple[InstrumentStrategyRecord, ...]:
    """引用该标的的所有策略，按策略聚合；版本集合用于继续查最近回测。"""

    symbol = inst_id.strip() if isinstance(inst_id, str) else ""
    if not symbol:
        raise ValidationError("标的标识不能为空")
    with session_scope() as session:
        linked = session.execute(
            select(StrategyInstrumentRow.strategy_version_id, StrategyVersionRow.strategy_id)
            .join(
                StrategyVersionRow,
                StrategyVersionRow.id == StrategyInstrumentRow.strategy_version_id,
            )
            .where(StrategyInstrumentRow.instrument_id == symbol)
            .order_by(StrategyVersionRow.version.desc())
        ).all()
        if not linked:
            return ()
        grouped: dict[str, list[str]] = {}
        for version_id, strategy_id in linked:
            grouped.setdefault(strategy_id, []).append(version_id)
        rows = list(
            session.scalars(
                select(UserStrategyRow)
                .where(UserStrategyRow.id.in_(list(grouped)))
                .order_by(UserStrategyRow.created_at.desc(), UserStrategyRow.id)
            )
        )
        records = _records(session, rows)
    return tuple(
        InstrumentStrategyRecord(strategy=record, version_ids=tuple(grouped[record.id]))
        for record in records
    )


def link_backtest(version_id: str, run_id: str) -> bool:
    """把一次回测登记到策略版本；重复登记是幂等的，返回是否新插入。"""

    if not version_id or not run_id:
        raise ValidationError("回测关联的版本与运行标识都不能为空")
    with session_scope() as session:
        if session.get(StrategyVersionRow, version_id) is None:
            raise ValidationError(f"未找到策略版本: {version_id}")
        statement = (
            postgresql_insert(StrategyLinkedBacktestRow)
            .values(
                strategy_version_id=version_id,
                backtest_run_id=run_id,
                created_at=_now(),
            )
            .on_conflict_do_nothing(index_elements=["strategy_version_id", "backtest_run_id"])
            .returning(StrategyLinkedBacktestRow.strategy_version_id)
        )
        return session.execute(statement).scalar_one_or_none() is not None


class _Unset:
    pass


_UNSET = _Unset()


def _insert_version(
    session: Session,
    strategy: UserStrategyRow,
    *,
    current: StrategyVersionRow | None,
    timeframe: str | None,
    direction: str | None,
    rule: Mapping[str, Any] | None,
    parameters: Mapping[str, Any] | None,
    sizing: Mapping[str, Any] | _Unset | None,
    cost_model: Mapping[str, Any] | _Unset | None,
    change_note: str | None,
    instruments: Sequence[str] | None,
    now: datetime,
    current_instruments: Sequence[str] | None = None,
) -> StrategyVersionRow:
    effective_timeframe = (
        timeframe if timeframe is not None else current.timeframe if current else None
    )
    effective_direction = (
        direction if direction is not None else current.direction if current else None
    )
    if effective_timeframe is None or effective_direction is None:
        raise ValidationError("策略版本必须指定周期与方向")
    _require_timeframe(effective_timeframe)
    _require_direction(effective_direction)

    submitted_rule = rule is not None
    rule_source = rule if submitted_rule else _object(current.rule_json) if current else {}
    if not isinstance(rule_source, Mapping):
        raise ValidationError("rule_json 必须是 JSON 对象")
    if sizing is _UNSET:
        # 没有提交顶层仓位规则：规则里显式写了就沿用规则的值，否则沿用当前版本的列值。
        if "position_sizing" in rule_source:
            embedded = rule_source["position_sizing"]
            effective_sizing = None if embedded is None else validate_position_sizing(embedded)
        else:
            effective_sizing = _optional_object(current.position_sizing_json) if current else None
    elif sizing is None:
        effective_sizing = None
    else:
        declared_sizing = validate_position_sizing(sizing)
        # 只有本次显式提交了 rule_json 时，顶层值才需要与规则内的值一致；
        # 只提交顶层字段是调整仓位规则的正常用法，不能拿继承来的旧规则对照。
        if submitted_rule and "position_sizing" in rule_source:
            embedded = rule_source["position_sizing"]
            if embedded is not None and validate_position_sizing(embedded) != declared_sizing:
                raise ValidationError("position_sizing 与 rule_json.position_sizing 不一致")
        effective_sizing = declared_sizing
    rule_payload = dict(rule_source)
    if rule is not None:
        stated_timeframe = rule_payload.get("timeframe")
        stated_direction = rule_payload.get("direction")
        if stated_timeframe is not None and stated_timeframe != effective_timeframe:
            raise ValidationError(
                f"rule_json.timeframe 与版本周期不一致: "
                f"{stated_timeframe!r} != {effective_timeframe!r}"
            )
        if stated_direction is not None and stated_direction != effective_direction:
            raise ValidationError(
                f"rule_json.direction 与版本方向不一致: "
                f"{stated_direction!r} != {effective_direction!r}"
            )
    rule_payload["timeframe"] = effective_timeframe
    rule_payload["direction"] = effective_direction
    if effective_sizing is None:
        rule_payload.pop("position_sizing", None)
    else:
        rule_payload["position_sizing"] = validate_position_sizing(effective_sizing)
    normalized_rule, normalized_sizing = normalize_rule(
        rule_payload,
        timeframe=effective_timeframe,
        direction=effective_direction,
    )

    inherited_parameters = _object(current.parameters_json) if current else {}
    effective_parameters = parameters if parameters is not None else inherited_parameters
    if cost_model is _UNSET:
        effective_cost_model = _optional_object(current.cost_model_json) if current else None
    else:
        effective_cost_model = cost_model
    effective_instruments = (
        tuple(instruments) if instruments is not None else tuple(current_instruments or ())
    )
    next_version = (current.version + 1) if current is not None else 1
    row = StrategyVersionRow(
        id="sv_" + uuid4().hex[:24],
        strategy_id=strategy.id,
        version=next_version,
        timeframe=effective_timeframe,
        direction=effective_direction,
        rule_json=canonical_json(normalized_rule),
        parameters_json=canonical_json(_parameters(effective_parameters)),
        position_sizing_json=(
            None if normalized_sizing is None else canonical_json(normalized_sizing)
        ),
        cost_model_json=(
            None
            if effective_cost_model is None
            else canonical_json(_parameters(effective_cost_model))
        ),
        change_note=_require_change_note(change_note),
        created_at=now,
    )
    session.add(row)
    session.flush()
    _insert_instruments(session, row.id, effective_instruments, now)
    return row


def _insert_instruments(
    session: Session, version_id: str, instrument_ids: Sequence[str], now: datetime
) -> None:
    if not instrument_ids:
        return
    session.execute(
        postgresql_insert(StrategyInstrumentRow)
        .values(
            [
                {
                    "strategy_version_id": version_id,
                    "instrument_id": instrument_id,
                    "created_at": now,
                }
                for instrument_id in instrument_ids
            ]
        )
        .on_conflict_do_nothing(index_elements=["strategy_version_id", "instrument_id"])
    )


def _records(session: Session, rows: Sequence[UserStrategyRow]) -> tuple[StrategyRecord, ...]:
    if not rows:
        return ()
    ids = [row.id for row in rows]
    versions = list(
        session.scalars(
            select(StrategyVersionRow)
            .where(StrategyVersionRow.strategy_id.in_(ids))
            .order_by(StrategyVersionRow.version.desc())
        )
    )
    by_strategy: dict[str, list[StrategyVersionRow]] = {}
    for version in versions:
        by_strategy.setdefault(version.strategy_id, []).append(version)
    current_ids = [items[0].id for items in by_strategy.values() if items]
    instruments = _instruments_by_version(session, current_ids)
    records = []
    for row in rows:
        items = by_strategy.get(row.id, [])
        if not items:
            raise InvariantViolation(f"策略 {row.id} 没有任何版本")
        current = items[0]
        records.append(
            StrategyRecord(
                id=row.id,
                name=row.name,
                category=row.category,
                description=row.description,
                status=row.status,
                current_version_id=current.id,
                current_version=current.version,
                timeframe=current.timeframe,
                direction=current.direction,
                rule_json=_object(current.rule_json),
                parameters=_object(current.parameters_json),
                position_sizing=_optional_object(current.position_sizing_json),
                cost_model=_optional_object(current.cost_model_json),
                instrument_ids=instruments.get(current.id, ()),
                version_ids=tuple(item.id for item in items),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return tuple(records)


def _current_version(session: Session, strategy_id: str) -> StrategyVersionRow | None:
    return session.scalar(
        select(StrategyVersionRow)
        .where(StrategyVersionRow.strategy_id == strategy_id)
        .order_by(StrategyVersionRow.version.desc())
        .limit(1)
    )


def _instruments_by_version(
    session: Session, version_ids: Sequence[str]
) -> dict[str, tuple[str, ...]]:
    if not version_ids:
        return {}
    rows = session.execute(
        select(StrategyInstrumentRow.strategy_version_id, StrategyInstrumentRow.instrument_id)
        .where(StrategyInstrumentRow.strategy_version_id.in_(version_ids))
        .order_by(
            StrategyInstrumentRow.strategy_version_id,
            StrategyInstrumentRow.instrument_id,
        )
    ).all()
    grouped: dict[str, list[str]] = {}
    for version_id, instrument_id in rows:
        grouped.setdefault(version_id, []).append(instrument_id)
    return {key: tuple(value) for key, value in grouped.items()}


def _version_instruments(session: Session, version_id: str) -> tuple[str, ...]:
    return _instruments_by_version(session, [version_id]).get(version_id, ())


def _version_record(
    row: StrategyVersionRow, instrument_ids: Sequence[str]
) -> StrategyVersionRecord:
    return StrategyVersionRecord(
        version_id=row.id,
        strategy_id=row.strategy_id,
        version=row.version,
        timeframe=row.timeframe,
        direction=row.direction,
        rule_json=_object(row.rule_json),
        parameters=_object(row.parameters_json),
        position_sizing=_optional_object(row.position_sizing_json),
        cost_model=_optional_object(row.cost_model_json),
        change_note=row.change_note,
        instrument_ids=tuple(instrument_ids),
        created_at=row.created_at,
    )


def _prepare_rule(
    rule_json: Mapping[str, Any],
    *,
    timeframe: str,
    direction: str,
    position_sizing: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    payload = dict(rule_json) if isinstance(rule_json, Mapping) else rule_json
    embedded = payload.get("position_sizing") if isinstance(payload, Mapping) else None
    if embedded is not None:
        embedded = validate_position_sizing(embedded)
        payload = dict(payload)
        payload["position_sizing"] = embedded
    if position_sizing is not None:
        declared = validate_position_sizing(position_sizing)
        if embedded is not None and embedded != declared:
            raise ValidationError("position_sizing 与 rule_json.position_sizing 不一致")
        payload = dict(payload)
        payload["position_sizing"] = declared
    return normalize_rule(payload, timeframe=timeframe, direction=direction)


def _resolve_instruments(instrument_ids: Sequence[str]) -> tuple[str, ...]:
    if isinstance(instrument_ids, str):
        raise ValidationError("instrument_ids 必须是数组")
    if not isinstance(instrument_ids, Sequence):
        raise ValidationError("instrument_ids 必须是数组")
    ordered: list[str] = []
    for item in instrument_ids:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError("instrument_ids 只能包含非空字符串")
        symbol = item.strip()
        if symbol not in ordered:
            ordered.append(symbol)
    if not ordered:
        return ()
    known = {row.symbol for row in list_instruments()}
    missing = [symbol for symbol in ordered if symbol not in known]
    if missing:
        raise ValidationError(f"未找到标的: {', '.join(missing)}")
    return tuple(ordered)


def _parameters(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError("parameters 必须是 JSON 对象")
    result = dict(value)
    for key in result:
        if not isinstance(key, str) or not key:
            raise ValidationError("parameters 的键必须是非空字符串")
    try:
        canonical_json(result)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"parameters 必须是可序列化的 JSON 对象: {exc}") from None
    return result


def _object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise InvariantViolation(f"库内 JSON 无法解析: {value!r}") from exc
    if not isinstance(parsed, dict):
        raise InvariantViolation(f"库内 JSON 不是对象: {value!r}")
    return parsed


def _optional_object(value: str | None) -> dict[str, Any] | None:
    return None if value is None else _object(value)


def _require_name(value: Any) -> str:
    name = value.strip() if isinstance(value, str) else ""
    if not name:
        raise ValidationError("策略名称不能为空")
    if len(name) > 128:
        raise ValidationError(f"策略名称最长 128 个字符, 实际 {len(name)}")
    return name


def _require_category(value: Any) -> str:
    category = value.strip() if isinstance(value, str) else ""
    if not category:
        raise ValidationError("策略类别不能为空")
    if len(category) > 64:
        raise ValidationError(f"策略类别最长 64 个字符, 实际 {len(category)}")
    return category


def _require_description(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("策略描述必须是字符串")
    text = value.strip()
    return text or None


def _require_status(value: Any) -> str:
    if value not in STATUSES:
        raise ValidationError(f"不支持的策略状态 {value!r}; 支持: {', '.join(STATUSES)}")
    return value


def _require_timeframe(value: Any) -> None:
    if value not in TIMEFRAMES:
        raise ValidationError(f"不支持的周期 {value!r}; 支持: {', '.join(TIMEFRAMES)}")


def _require_direction(value: Any) -> None:
    if value not in DIRECTIONS:
        raise ValidationError(f"不支持的方向 {value!r}; 支持: {', '.join(DIRECTIONS)}")


def _require_change_note(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("变更说明必须是字符串")
    text = value.strip()
    if len(text) > 512:
        raise ValidationError(f"变更说明最长 512 个字符, 实际 {len(text)}")
    return text or None


def _reject_null_version_values(changes: Mapping[str, Any]) -> None:
    """版本字段里的 null 一律按不合法输入拒绝，不做「当作省略」的静默处理。"""

    nulls = sorted(
        key for key in _REQUIRED_VERSION_VALUES if key in changes and changes[key] is None
    )
    if nulls:
        raise ValidationError(f"这些字段不能为 null: {', '.join(nulls)}")


def _parse_cursor(cursor: str) -> tuple[datetime, str]:
    raw_time, _, strategy_id = cursor.partition(":")
    if not raw_time.isdigit() or len(raw_time) > 12:
        raise ValidationError(f"无效的分页游标: {cursor!r}")
    try:
        return datetime.fromtimestamp(int(raw_time), tz=UTC), strategy_id
    except (ValueError, TypeError, OSError, OverflowError) as exc:
        raise ValidationError(f"无效的分页游标: {cursor!r}") from exc


def _now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)
