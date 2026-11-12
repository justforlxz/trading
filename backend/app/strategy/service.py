"""策略实例与目标组合回放的编排：投影模板、读写实例、按历史行情重算目标组合。

本模块只做 IO 与事务边界：参数校验交给 `resolve_params`，组合计算交给模板的
`build`，相关性矩阵交给 `app.market.build_matrix`（纯计算，不重复读库）。

三件事各自只有一处实现：

1. **模板投影** —— 模板是代码事实（注册表在 import 时登记），表里的行是它的只读
   投影。写投影只发生在这里，实例的外键因此总是指向一行真实存在的模板。
2. **实例** —— 用户配置：参数、标的、启停。生命周期阶段不在本模块推进（只经审批
   状态机），这里只在创建时写入草稿阶段 `strategy_generation`。
3. **回放** —— 在区间内的每一根 K 线上构造只读视图、调用模板、记录目标组合。视图
   只用该时点**及之前**的 K 线，因此回放不读未来数据；同一份库上重复回放得到同一
   份目标组合，其规范化 JSON 的 sha256 相同。

回放的是目标组合而不是信号：每个时点产出的是「多腿、方向、目标权重」，折线画的是
这些组合的逐点净敞口。净值与收益属于回测（T4.x），本模块不算，也不引入资金假设。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.core import Bar, Conflict, DataUnavailable, InvariantViolation, ValidationError
from app.db import session_scope
from app.indicators import Param, ParamValue
from app.instrument import Instrument, list_instruments
from app.market import asset_session, build_matrix, load_candles, primary_source
from app.shared import CANONICAL_BARS, normalize_bar
from app.strategy.model import StrategyInstanceRow, StrategyReplayRow, StrategyTemplateRow
from app.strategy.params import resolve_params
from app.strategy.protocol import Template
from app.strategy.registry import get_template, list_templates
from app.strategy.target import TargetPortfolio
from app.strategy.view import MarketView

__all__ = [
    "DEFAULT_EXECUTION_MODE",
    "DEFAULT_STATUS",
    "MAX_REPLAY_POINTS",
    "REPLAY_CORRELATION_WINDOW",
    "InstanceRecord",
    "ReplayLeg",
    "ReplayOutcome",
    "ReplayPoint",
    "ReplayRecord",
    "TemplateDefinition",
    "create_instance",
    "delete_instance",
    "evaluate_replay",
    "get_instance",
    "list_instances",
    "list_replays",
    "prepare_replay",
    "project_templates",
    "save_replay",
    "update_instance",
]

# 新建实例落在生命周期的草稿阶段：机会发现 → **策略生成** → 人工审核 → …
# 与 `docs/prd/decisions.md` D7 的取值逐字一致。
DEFAULT_STATUS = "strategy_generation"

# 新建实例的执行方式是人工：模拟与实盘执行属 P3，本节点只记录实例配置。
DEFAULT_EXECUTION_MODE = "manual"

# 回放用的相关性窗口：它只决定「用最近多少个样本算系数」，与模板的均值回归窗口
# 不是同一个参数，因此不跟随实例参数（模板协议也没有声明它需要多长的相关性窗口）。
# 20 与模板默认窗口同量级：样本够多才有稳定的系数，又不会把窗口推到超出常见历史。
REPLAY_CORRELATION_WINDOW = 20

# 一次回放允许的时点数上限。回放的每个时点都要重建一次视图与相关性矩阵（这两步在
# `app.strategy.view` / `app.market.matrix` 里，各按该时点的全部历史走一遍），因此
# 总耗时随「时点数 × 时点平均 K 线数」增长：本机两个标的、1000 个日线时点约 0.8 秒，
# 而 1 分钟周期 90 天有 13 万个时点（约数十小时）。同步端点不能接受这种量级，因此
# 超过上限时直接报错，让调用方缩小区间或改用更粗的周期，而不是占住线程直到客户端
# 超时。
MAX_REPLAY_POINTS = 1000

# 对外发布的权重与净敞口按小数点后 12 位收敛。契约的 `DecimalString`
# （`app/api/schemas/common.py` 的 `DECIMAL_PATTERN`）最多允许 12 位小数，而权重是
# 除法算出的 28 位有效数字；不收敛会让响应模型校验失败（500），落库的 JSON 也会变成
# 一条读不出来的记录。收敛只在这里做一次，落库、响应与规范化 JSON 共用同一份数值。
_WEIGHT_QUANTUM = Decimal("0.000000000001")

_SIDES = ("long", "short")


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    """一个组合模板在目录接口里的完整声明：登记名、标题、版本、说明与参数表。"""

    strategy_id: str
    name: str
    version: str
    summary: str
    params: tuple[Param, ...]
    bars: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InstanceRecord:
    """一条策略实例：参数已补齐为完整参数表，标的是交易所标识的有序去重序列。

    后半段的四个字段是生命周期推进留下的凭据：审核通过的人与时刻、达标报告编号、实盘
    授权时刻。它们由审批状态机（`app.strategy.approval`）写入，读回时原样报出；没发生
    的推进是 `None`。
    """

    instance_id: str
    strategy_id: str
    strategy_version: str
    name: str
    bar: str
    params: Mapping[str, ParamValue]
    inst_ids: tuple[str, ...]
    lifecycle_status: str
    enabled: bool
    execution_mode: str
    latest_signal_at: datetime | None
    created_at: datetime
    updated_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    validation_report_id: str | None = None
    live_authorized_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReplayPoint:
    """回放曲线上的一个点：该时点的目标组合有几条腿、净敞口是多少。"""

    as_of: datetime
    net_exposure: Decimal
    leg_count: int


@dataclass(frozen=True, slots=True)
class ReplayLeg:
    """回放结果里的一条腿：产品键、可交易标的、方向与目标权重。

    `product_key` 是规范化 JSON 的排序键，`inst_id` / `inst_type` 是界面上要显示的
    可交易形态。两者都在这里，界面不必自己拆标识。
    """

    product_key: str
    inst_id: str
    inst_type: str
    side: str
    target_weight: Decimal


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    """一次回放的计算结果（尚未落库）：目标组合 + 逐点净敞口 + 规范化 JSON 与哈希。"""

    legs: tuple[ReplayLeg, ...]
    net_exposure: Decimal
    canonical_json: str
    target_hash: str
    points: tuple[ReplayPoint, ...]


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    """一条已落库的回放记录：区间、目标组合、逐点净敞口与创建时刻。"""

    replay_id: str
    instance_id: str
    strategy_id: str
    bar: str
    start: datetime
    end: datetime
    legs: tuple[ReplayLeg, ...]
    net_exposure: Decimal
    canonical_json: str
    target_hash: str
    points: tuple[ReplayPoint, ...]
    created_at: datetime


def project_templates() -> tuple[TemplateDefinition, ...]:
    """把代码注册表里的模板写进只读投影表，返回目录内容。

    幂等：登记名已存在且版本、标题、说明都没变时不写库；模板升级（版本号变了）才
    更新那一行。实例的外键依赖这张表，因此建实例与列目录都先过这里一次。

    插入走 `ON CONFLICT DO NOTHING`：两个请求同时打开页面（或同时建实例）时都可能
    看到「还没有这一行」，唯一约束会让后提交的那个失败；忽略冲突后两边都成功，接
    下来的更新用同一份内容覆盖，结果一致。
    """

    definitions = tuple(_definition(row) for row in _registered_templates())
    updated_at = _epoch(_now())
    with session_scope() as session:
        existing = {row.strategy_id: row for row in session.scalars(select(StrategyTemplateRow))}
        for definition in definitions:
            row = existing.get(definition.strategy_id)
            if row is None:
                session.execute(
                    postgresql_insert(StrategyTemplateRow)
                    .values(
                        strategy_id=definition.strategy_id,
                        name=definition.name,
                        version=definition.version,
                        summary=definition.summary,
                        updated_at=updated_at,
                    )
                    .on_conflict_do_nothing(index_elements=["strategy_id"])
                )
                continue
            if (row.name, row.version, row.summary) == (
                definition.name,
                definition.version,
                definition.summary,
            ):
                continue
            row.name = definition.name
            row.version = definition.version
            row.summary = definition.summary
            row.updated_at = updated_at
    return definitions


def list_instances(
    *,
    strategy_id: str | None = None,
    enabled: bool | None = None,
    limit: int = 100,
) -> tuple[tuple[InstanceRecord, ...], int]:
    """按过滤条件列出实例，返回（本页记录，符合条件的总条数）。

    排序是「创建时刻倒序、标识升序」：同一份库两次读取顺序一致。
    """

    _require_limit(limit)
    conditions = []
    if strategy_id is not None:
        conditions.append(StrategyInstanceRow.strategy_id == strategy_id)
    if enabled is not None:
        conditions.append(StrategyInstanceRow.enabled == enabled)

    statement = (
        select(StrategyInstanceRow)
        .where(*conditions)
        .order_by(StrategyInstanceRow.created_at.desc(), StrategyInstanceRow.instance_id)
        .limit(limit)
    )
    with session_scope() as session:
        rows = list(session.scalars(statement))
        counted = select(func.count()).select_from(StrategyInstanceRow).where(*conditions)
        total = session.scalar(counted)
    return tuple(_instance_record(row) for row in rows), total or 0


def get_instance(instance_id: str) -> InstanceRecord | None:
    """按标识取一条实例；不存在返回 `None`，由调用方决定怎么报错。"""

    with session_scope() as session:
        row = session.get(StrategyInstanceRow, instance_id)
        return None if row is None else _instance_record(row)


def create_instance(
    *,
    strategy_id: str,
    name: str,
    bar: str,
    params: Mapping[str, ParamValue] | None = None,
    inst_ids: Sequence[str],
) -> InstanceRecord:
    """建一个实例：模板必须已登记、参数必须过模板 schema、标的必须已同步。

    `strategy_version` 记下创建时模板的版本：模板之后升级不回填这一列，历史实例
    仍报自己那一版。
    """

    definitions = {item.strategy_id: item for item in project_templates()}
    definition = definitions.get(strategy_id)
    if definition is None:
        raise ValidationError(
            f"未知的策略模板 {strategy_id!r}; 支持: {', '.join(sorted(definitions))}"
        )

    resolved = resolve_params(definition.params, params)
    instruments = _instruments(inst_ids)
    moment = _now()
    row = StrategyInstanceRow(
        instance_id="si_" + uuid4().hex[:24],
        strategy_id=definition.strategy_id,
        strategy_version=definition.version,
        name=_require_name(name),
        bar=_require_bar(bar),
        params=_params_json(resolved),
        inst_ids=_inst_ids_json(instruments),
        lifecycle_status=DEFAULT_STATUS,
        enabled=True,
        execution_mode=DEFAULT_EXECUTION_MODE,
        latest_signal_at=None,
        created_at=_epoch(moment),
        updated_at=_epoch(moment),
    )
    with session_scope() as session:
        session.add(row)
    return _instance_record(row)


def update_instance(
    instance_id: str,
    *,
    name: str | None = None,
    params: Mapping[str, ParamValue] | None = None,
    inst_ids: Sequence[str] | None = None,
    enabled: bool | None = None,
) -> InstanceRecord | None:
    """PATCH 语义：只落显式提交的字段；实例不存在返回 `None`。

    `params` 按「已有参数 + 本次提交」合并后再过模板 schema：一次只改一个参数的人
    不用把其余参数一起报上来。生命周期阶段不在这条路径上改（见
    `StrategyInstanceUpdateRequest`），`enabled` 只控制启停。
    """

    with session_scope() as session:
        row = session.get(StrategyInstanceRow, instance_id)
        if row is None:
            return None
        if name is not None:
            row.name = _require_name(name)
        if params is not None:
            merged = {**_json_object(row.params), **params}
            row.params = _params_json(
                resolve_params(_template(row.strategy_id).param_schema, merged)
            )
        if inst_ids is not None:
            row.inst_ids = _inst_ids_json(_instruments(inst_ids))
        if enabled is not None:
            row.enabled = bool(enabled)
        row.updated_at = _epoch(_now())
    return _instance_record(row)


def delete_instance(instance_id: str) -> bool:
    """删除实例；不存在返回 `False`。

    回放记录在实例删掉之后没有独立意义，由 `strategy_replays.instance_id` 上的
    `ON DELETE CASCADE` 一并删除——删除语义只有迁移里那一处，这里不再重复一遍。
    """

    with session_scope() as session:
        row = session.get(StrategyInstanceRow, instance_id)
        if row is None:
            return False
        session.delete(row)
    return True


def evaluate_replay(
    instance: InstanceRecord,
    *,
    start: datetime,
    end: datetime,
) -> ReplayOutcome:
    """在 `[start, end]` 上重算目标组合，返回目标组合与逐点净敞口（不写库）。

    每个时点只喂该时点**及之前**的 K 线，因此没有前视偏差；来源按「资产时段 ×
    资产类别」逐时点解析，不把不同来源的序列拼进同一次计算。K 线在进入循环之前
    一次读好，循环内用只前进的游标取前缀，不在每个时点重新过滤整段序列。

    时点数超过 `MAX_REPLAY_POINTS` 直接报错：单个时点要重建一次视图与相关性矩阵，
    代价与该时点的历史长度成正比，放行下去会让同步端点长时间占住线程。
    """

    _require_window(start, end)
    template = _template(instance.strategy_id)
    instruments = _instruments(instance.inst_ids)
    loaded = _load_series(instruments, instance.bar, start=start, end=end)
    timeline = sorted(
        {
            candle.open_time
            for by_source in loaded.values()
            for candles in by_source.values()
            for candle in candles
        }
    )
    if not timeline:
        raise DataUnavailable(
            f"回放区间 {_iso(start)} ~ {_iso(end)} 内没有 {instance.bar} K 线, 请先同步行情"
        )
    if len(timeline) > MAX_REPLAY_POINTS:
        raise ValidationError(
            f"回放区间包含 {len(timeline)} 个 {instance.bar} 时点, 超过上限 "
            f"{MAX_REPLAY_POINTS}; 请缩小区间或改用更粗的周期"
        )

    builder = template(bar=instance.bar, **instance.params)
    by_key = {instrument.product_key: instrument for instrument in instruments}
    cursors: dict[tuple[str, str], _SeriesCursor] = {}
    portfolio: TargetPortfolio | None = None
    points: list[ReplayPoint] = []
    for moment in timeline:
        portfolio = builder.build(_view(moment, instruments, loaded, cursors, instance.bar))
        points.append(
            ReplayPoint(
                as_of=moment,
                net_exposure=_weight(portfolio.net_exposure),
                leg_count=len(portfolio.legs),
            )
        )
    assert portfolio is not None  # timeline 非空, 循环至少跑一次

    legs = tuple(
        _replay_leg(leg.product_key, leg.side, leg.target_weight, by_key) for leg in portfolio.legs
    )
    net_exposure = _net_from_legs(legs)
    canonical = _canonical_json(legs, net_exposure)
    return ReplayOutcome(
        legs=legs,
        net_exposure=net_exposure,
        canonical_json=canonical,
        target_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        points=tuple(points),
    )


def prepare_replay(
    instance_id: str,
    *,
    start: datetime,
    end: datetime,
) -> ReplayRecord | None:
    """算好一次回放并返回「待落库」的记录；实例不存在返回 `None`。

    停用的实例直接报冲突（409）：静默返回空结果会与「这个实例在这个区间上没有信号」
    混成同一件事。

    只计算、不写库：端点先把它映射成契约模型（响应校验可能失败），成功之后才调用
    `save_replay`。这样契约层拒绝的请求不会在库里留下一行读不出来的记录——上一次功能
    检测遇到的正是「500 之后仍落库，历史接口从此打不开」。
    """

    instance = get_instance(instance_id)
    if instance is None:
        return None
    if not instance.enabled:
        raise Conflict(f"策略实例 {instance_id} 已停用, 不能回放")

    outcome = evaluate_replay(instance, start=start, end=end)
    created = _now()
    moment_start = _moment(start)
    moment_end = _moment(end)
    replay_id = "srp_" + uuid4().hex[:24]
    return ReplayRecord(
        replay_id=replay_id,
        instance_id=instance.instance_id,
        strategy_id=instance.strategy_id,
        bar=instance.bar,
        start=moment_start,
        end=moment_end,
        legs=outcome.legs,
        net_exposure=outcome.net_exposure,
        canonical_json=outcome.canonical_json,
        target_hash=outcome.target_hash,
        points=outcome.points,
        created_at=created,
    )


def save_replay(record: ReplayRecord) -> None:
    """把一条待落库的回放记录写进 `strategy_replays`。

    每次回放都留一行执行记录；两次回放是否算出同一份目标组合由 `target_hash` 回答，
    而不是靠覆盖上一行来假装一致。
    """

    row = StrategyReplayRow(
        replay_id=record.replay_id,
        instance_id=record.instance_id,
        bar=record.bar,
        start_at=_epoch(record.start),
        end_at=_epoch(record.end),
        result_json=_result_json(record.legs, record.net_exposure),
        target_hash=record.target_hash,
        points_json=_points_json(record.points),
        created_at=_epoch(record.created_at),
    )
    with session_scope() as session:
        session.add(row)


def list_replays(
    instance_id: str,
    *,
    limit: int = 50,
) -> tuple[tuple[ReplayRecord, ...], int] | None:
    """按实例列出回放记录，返回（本页记录，总条数）；实例不存在返回 `None`。

    实例不存在与「实例存在但还没回放过」不是一回事：前者由端点回答 404，后者是
    空列表。错误分支合流会让人分不清「这个实例没了」和「还没跑过回放」。
    """

    _require_limit(limit)
    with session_scope() as session:
        instance = session.get(StrategyInstanceRow, instance_id)
        if instance is None:
            return None
        strategy_id = instance.strategy_id
        rows = list(
            session.scalars(
                select(StrategyReplayRow)
                .where(StrategyReplayRow.instance_id == instance_id)
                .order_by(StrategyReplayRow.created_at.desc(), StrategyReplayRow.replay_id)
                .limit(limit)
            )
        )
        counted = (
            select(func.count())
            .select_from(StrategyReplayRow)
            .where(StrategyReplayRow.instance_id == instance_id)
        )
        total = session.scalar(counted)
    return (
        tuple(_replay_record(row, strategy_id=strategy_id) for row in rows),
        total or 0,
    )


def _registered_templates() -> tuple[type[Template], ...]:
    """注册表里全部模板类，按登记名排序。"""

    return tuple(get_template(name) for name in list_templates())


def _definition(template: type[Template]) -> TemplateDefinition:
    """模板类 → 目录条目。

    `bars` 列出全部规范周期：模板在构造时接受任意规范周期，具体用哪个由实例配置
    决定。`emitted_actions` 不在域里声明，也不在这里编——模板产出目标组合，不产出
    单标的动作，端点按空列表回答。
    """

    return TemplateDefinition(
        strategy_id=template.meta.name,
        name=template.meta.title,
        version=template.meta.version,
        summary=template.meta.summary,
        params=tuple(template.param_schema),
        bars=CANONICAL_BARS,
    )


def _template(strategy_id: str) -> type[Template]:
    """实例引用的模板类；模板已从代码里消失属于「不该发生」，单独报错。"""

    try:
        return get_template(strategy_id)
    except ValidationError as exc:
        raise InvariantViolation(f"实例引用的模板 {strategy_id!r} 已不在注册表里: {exc}") from None


def _instruments(inst_ids: Sequence[str]) -> tuple[Instrument, ...]:
    """把实例配置的交易所标识解析成标的行，顺序按配置顺序、重复项只留一次。

    同一个产品的两种形态不能同时进一个实例：视图按产品键组织，两条腿指向同一个
    产品键会互相覆盖，而目标组合也要求一个产品只有一条腿。
    """

    if not inst_ids:
        raise ValidationError("实例至少要选择一个标的")
    index = {row.symbol: row for row in list_instruments()}
    ordered = tuple(dict.fromkeys(inst_ids))
    missing = [inst_id for inst_id in ordered if inst_id not in index]
    if missing:
        raise ValidationError(f"未找到标的:{', '.join(missing)}")

    instruments = tuple(index[inst_id] for inst_id in ordered)
    keys = [instrument.product_key for instrument in instruments]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise ValidationError(f"同一产品的两种形态不能同时加入一个实例:{', '.join(duplicated)}")
    return instruments


def _load_series(
    instruments: Sequence[Instrument],
    bar: str,
    *,
    start: datetime,
    end: datetime,
) -> dict[str, dict[str, list[Bar]]]:
    """一次读出区间内全部 K 线，按「标的 → 来源 → K 线」组织。

    来源不在读取时筛：回放逐时点按「资产时段 × 资产类别」决定读哪一条序列，
    因此每个来源的分组都要留在内存里。
    """

    end_exclusive = _moment(end) + timedelta(seconds=1)
    loaded: dict[str, dict[str, list[Bar]]] = {}
    for instrument in instruments:
        by_source: dict[str, list[Bar]] = {}
        for candle in load_candles(instrument.symbol, bar, start=_moment(start), end=end_exclusive):
            by_source.setdefault(candle.source, []).append(candle)
        loaded[instrument.symbol] = by_source
    return loaded


class _SeriesCursor:
    """一条「标的 + 来源」序列的只进游标，附带它的收盘价前缀。

    时间轴升序，因此每条序列在一个回放里只被扫一遍：游标推进到当前时点时把新出现的
    K 线追加到 `closes`，视图拿到的是同一份前缀，不必每个时点重建一次。收盘价用
    `float` 保留 `app.market` 的相关性口径（无量纲统计量，与金额精度无关）。
    """

    __slots__ = ("closes", "index", "series")

    def __init__(self, series: Sequence[Bar]) -> None:
        self.series = series
        self.index = 0
        self.closes: list[tuple[datetime, float]] = []

    def advance(self, moment: datetime) -> int:
        """推进到 `moment`（含），返回前缀长度；已经推进过的位置不重复扫描。"""

        series = self.series
        while self.index < len(series) and series[self.index].open_time <= moment:
            candle = series[self.index]
            self.closes.append((candle.open_time, float(candle.close)))
            self.index += 1
        return self.index


def _view(
    moment: datetime,
    instruments: Sequence[Instrument],
    loaded: Mapping[str, Mapping[str, Sequence[Bar]]],
    cursors: dict[tuple[str, str], _SeriesCursor],
    bar: str,
) -> MarketView:
    """某个时点的只读视图：只用该时点及之前的 K 线，矩阵与视图同一时点。

    `moment` 就是当前这根 K 线的 `open_time`，视图里包含这根已收盘的 K 线：回放记录
    的 `as_of` 因此是「这根 K 线的开盘时刻」，不是决策时刻，下游不要拿它当成「此刻
    只知道之前的数据」。
    """

    candles: dict[str, dict[str, Sequence[Bar]]] = {}
    closes: dict[str, list[tuple[datetime, float]]] = {}
    for instrument in instruments:
        source = _source_at(instrument, moment)
        key = (instrument.symbol, source)
        series = loaded.get(instrument.symbol, {}).get(source, ())
        cursor = cursors.get(key)
        if cursor is None:
            cursor = cursors[key] = _SeriesCursor(series)
        rows = series[: cursor.advance(moment)]
        candles[instrument.product_key] = {bar: rows}
        closes[instrument.product_key] = cursor.closes

    return MarketView(
        as_of=moment,
        candles=candles,
        matrix=build_matrix(
            list(closes),
            closes,
            bar=bar,
            window=REPLAY_CORRELATION_WINDOW,
            as_of=moment,
        ),
    )


def _source_at(instrument: Instrument, moment: datetime) -> str:
    """该时点的有效行情来源，与实时读取走同一条「资产时段 × 资产类别」规则。"""

    session = asset_session(instrument.asset_type, moment, inst_type=instrument.inst_type)
    return primary_source(session, instrument.asset_type, instrument.inst_type)


def _replay_leg(
    product_key: str,
    side: str,
    target_weight: Decimal,
    by_key: Mapping[str, Instrument],
) -> ReplayLeg:
    """目标组合的一条腿 → 回放记录的一条腿；产品键必须在实例的标的内。"""

    instrument = by_key.get(product_key)
    if instrument is None:
        raise InvariantViolation(f"模板产出的腿 {product_key!r} 不在实例选择的标的内")
    if side not in _SIDES:
        raise InvariantViolation(f"目标腿的方向只能是 {_SIDES}, 实际 {side!r}")
    return ReplayLeg(
        product_key=product_key,
        inst_id=instrument.symbol,
        inst_type=instrument.inst_type,
        side=side,
        target_weight=_weight(target_weight),
    )


def _canonical_json(legs: Sequence[ReplayLeg], net_exposure: Decimal) -> str:
    """目标组合的规范化 JSON：腿按 `product_key` 排序、键排序、无多余空白。

    排序是复现判据的一部分：腿的顺序由模板决定，但「同一份目标组合」不该因为顺序
    不同而得到不同的哈希。
    """

    payload = {
        "legs": [
            {
                "product_key": leg.product_key,
                "side": leg.side,
                "target_weight": _decimal_text(leg.target_weight),
            }
            for leg in sorted(legs, key=lambda item: item.product_key)
        ],
        "net_exposure": _decimal_text(net_exposure),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _result_json(legs: Sequence[ReplayLeg], net_exposure: Decimal) -> str:
    """落库的目标组合：在规范化 JSON 的腿上补出可交易形态，供界面直接显示。"""

    payload = {
        "legs": [
            {
                "inst_id": leg.inst_id,
                "inst_type": leg.inst_type,
                "product_key": leg.product_key,
                "side": leg.side,
                "target_weight": _decimal_text(leg.target_weight),
            }
            for leg in sorted(legs, key=lambda item: item.product_key)
        ],
        "net_exposure": _decimal_text(net_exposure),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _points_json(points: Sequence[ReplayPoint]) -> str:
    """落库的逐点曲线：时间存 epoch 秒，与库内其余时间列同口径。"""

    return json.dumps(
        [
            {
                "as_of": _epoch(point.as_of),
                "leg_count": point.leg_count,
                "net_exposure": _decimal_text(point.net_exposure),
            }
            for point in points
        ],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _params_json(params: Mapping[str, ParamValue]) -> str:
    """参数 → JSON 文本：键排序，同一组参数两次序列化逐字相同。"""

    return json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _inst_ids_json(instruments: Sequence[Instrument]) -> str:
    """标的 → JSON 数组：按配置顺序保留，用于「这个实例看哪些标的」。"""

    return json.dumps(
        [instrument.symbol for instrument in instruments],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _json_object(value: str) -> dict[str, ParamValue]:
    """库里的 JSON 对象文本 → 字典；坏数据属于「不该发生」。"""

    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise InvariantViolation(f"实例参数不是 JSON 对象:{value!r}")
    return parsed


def _instance_record(row: StrategyInstanceRow) -> InstanceRecord:
    """库里的行 → 域记录；参数与标的从 JSON 还原。"""

    return InstanceRecord(
        instance_id=row.instance_id,
        strategy_id=row.strategy_id,
        strategy_version=row.strategy_version,
        name=row.name,
        bar=row.bar,
        params=MappingProxyType(_json_object(row.params)),
        inst_ids=tuple(json.loads(row.inst_ids)),
        lifecycle_status=row.lifecycle_status,
        enabled=row.enabled,
        execution_mode=row.execution_mode,
        latest_signal_at=(
            None if row.latest_signal_at is None else _from_epoch(row.latest_signal_at)
        ),
        created_at=_from_epoch(row.created_at),
        updated_at=_from_epoch(row.updated_at),
        approved_by=row.approved_by,
        approved_at=None if row.approved_at is None else _from_epoch(row.approved_at),
        validation_report_id=row.validation_report_id,
        live_authorized_at=(
            None if row.live_authorized_at is None else _from_epoch(row.live_authorized_at)
        ),
    )


def _replay_record(row: StrategyReplayRow, *, strategy_id: str) -> ReplayRecord:
    """库里的回放行 → 域记录；规范化 JSON 由库里的腿重新推出，与写入时同一口径。"""

    payload = json.loads(row.result_json)
    legs = tuple(
        ReplayLeg(
            product_key=item["product_key"],
            inst_id=item["inst_id"],
            inst_type=item["inst_type"],
            side=item["side"],
            target_weight=Decimal(item["target_weight"]),
        )
        for item in payload["legs"]
    )
    net_exposure = Decimal(payload["net_exposure"])
    points = tuple(
        ReplayPoint(
            as_of=_from_epoch(item["as_of"]),
            net_exposure=Decimal(item["net_exposure"]),
            leg_count=int(item["leg_count"]),
        )
        for item in json.loads(row.points_json)
    )
    return ReplayRecord(
        replay_id=row.replay_id,
        instance_id=row.instance_id,
        strategy_id=strategy_id,
        bar=row.bar,
        start=_from_epoch(row.start_at),
        end=_from_epoch(row.end_at),
        legs=legs,
        net_exposure=net_exposure,
        canonical_json=_canonical_json(legs, net_exposure),
        target_hash=row.target_hash,
        points=points,
        created_at=_from_epoch(row.created_at),
    )


def _require_name(value: str) -> str:
    """实例名：去空白后不能为空，长度不超过表的列宽。"""

    name = value.strip() if isinstance(value, str) else ""
    if not name:
        raise ValidationError("实例名称不能为空")
    if len(name) > 128:
        raise ValidationError(f"实例名称最长 128 个字符, 实际 {len(name)}")
    return name


def _require_bar(bar: str) -> str:
    """周期必须是规范写法；别名只允许出现在交易所适配层。"""

    try:
        return normalize_bar(bar)
    except ValueError as exc:
        raise ValidationError(str(exc)) from None


def _require_window(start: datetime, end: datetime) -> None:
    """回放区间：两端都要带时区，且 start 早于 end。"""

    if start.tzinfo is None or end.tzinfo is None:
        raise ValidationError("回放区间必须带时区")
    if _moment(start) >= _moment(end):
        raise ValidationError(f"回放区间起点必须早于终点:{_iso(start)} >= {_iso(end)}")


def _require_limit(limit: int) -> None:
    if limit < 1:
        raise ValidationError(f"条数上限必须是正整数:{limit}")


def _now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


def _moment(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(microsecond=0)


def _epoch(value: datetime) -> int:
    return int(_moment(value).timestamp())


def _from_epoch(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


def _iso(value: datetime) -> str:
    return _moment(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _weight(value: Decimal) -> Decimal:
    """权重与敞口按契约允许的最大精度收敛（小数点后 12 位）。"""

    return value.quantize(_WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)


def _net_from_legs(legs: Sequence[ReplayLeg]) -> Decimal:
    """净敞口由收敛后的腿权重推出：响应里的腿与净敞口因此始终自洽。"""

    total = Decimal(0)
    for leg in legs:
        total += leg.target_weight if leg.side == "long" else -leg.target_weight
    return total


def _decimal_text(value: Decimal) -> str:
    """`Decimal` → 定点字符串；与 API 边界上的 `decimal_str` 同一口径。"""

    return format(value.normalize(), "f")
