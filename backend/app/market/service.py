"""市场域对外编排：可用区间、完整性报告、两标的相关性、相关矩阵快照、市场总览与当前行情。

读侧只读库，不做任何补齐或插值：缺多少根就报多少根，可用区间就是库里真实的首末。
相关性在这里完成「按 open_time 对齐两条序列」的编排，系数仍由纯函数计算。
矩阵快照在这里完成「矩阵标识 → 产品键」的换算与幂等写入，数值仍由矩阵模块算。
「当前有效行情」在这里完成「查标的 → 判时段 → 选来源 → 取最新一根」的编排，
时段与来源的选择本身仍是 `app.market.session` 的纯函数。
市场总览在这里完成「取该类别可交易标的 → 逐个解析来源 → 各取最近若干根」的编排，
涨跌家数与同向程度仍由 `app.market.breadth` 的纯函数算。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.core import Bar, ValidationError
from app.db import session_scope
from app.instrument import Instrument, list_tradable, resolve_instrument
from app.market.breadth import Breadth, Resonance, advance_decline, resonance_strength
from app.market.candles import duplicate_open_times, expected_open_times, find_gaps
from app.market.correlation import METHODS, correlate, p_value
from app.market.matrix import Matrix
from app.market.model import Candle, CorrelationSnapshot, from_epoch, to_epoch
from app.market.session import UNKNOWN_ASSET, asset_session, day_asset_type, primary_source
from app.market.sync import candle_sources, data_range, load_candles, normalize_bar_or_raise
from app.shared import bar_seconds

# 快照单条 INSERT 的行数上限：PostgreSQL 单条语句最多 65535 个绑定参数，每行 7 个值，
# 1000 行留足余量；全市场矩阵（上千个产品）也不会撞上参数上限。
SNAPSHOT_BATCH_SIZE = 1000

# 共振窗口的根数：契约里的 `/market/overview` 没有 window 参数，窗口只能是固定值，
# 取了多少根就写进响应的 `resonance.window`，不隐瞒口径。
RESONANCE_WINDOW = 20


@dataclass(frozen=True, slots=True)
class CandleGap:
    """一段连续缺失的窗口 `[start, end)` 与其中的缺失根数。"""

    start: datetime
    end: datetime
    missing: int


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """库内某标的某一周期的完整性：真实首末、应有/实有根数、缺口、重复与最后同步时间。"""

    symbol: str
    bar: str
    start: datetime | None
    end: datetime | None
    expected: int
    present: int
    missing: int
    gaps: tuple[CandleGap, ...]
    duplicates: tuple[datetime, ...]
    last_synced_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PairCorrelation:
    """两个标的按 open_time 对齐后的相关系数与显著性。"""

    symbol_a: str
    symbol_b: str
    bar: str
    method: str
    sample_size: int
    coefficient: float | None
    p_value: float | None


@dataclass(frozen=True, slots=True)
class MarketOverview:
    """某一类别在某一时点的横截面总览：广度与共振。

    `breadth` 与 `resonance` 用的是同一批参与标的（窗口内至少有 2 根 K 线的该类别
    标的），因此两个 `participants` 恒相等；共振窗口固定为 `RESONANCE_WINDOW`。
    """

    inst_type: str
    bar: str
    as_of: datetime
    breadth: Breadth
    resonance: Resonance


def integrity(symbol: str, bar: str, *, source: str | None = None) -> IntegrityReport:
    """检测库内缺口与重复；只读，不会写入任何补齐数据。

    统计区间取库里真实的首末 K 线（`[first, last + 一个周期)`），
    因此「可用区间」与缺口报告是同一份事实。日线的期望序列按**该序列所属市场**的
    交易日排（代理行情按美股时段、OKX 行情按 UTC+8 零点），来源不同不能共用一个网格。
    """

    canonical = normalize_bar_or_raise(bar)
    first_last = data_range(symbol, canonical, source=source)
    last_synced_at = _last_synced_at(symbol, canonical, source)
    if first_last is None:
        return IntegrityReport(
            symbol=symbol,
            bar=canonical,
            start=None,
            end=None,
            expected=0,
            present=0,
            missing=0,
            gaps=(),
            duplicates=(),
            last_synced_at=last_synced_at,
        )

    first, last = first_last
    step = timedelta(seconds=bar_seconds(canonical))
    window_end = last + step
    actual = [
        candle.open_time
        for candle in load_candles(symbol, canonical, start=first, end=window_end, source=source)
    ]
    boundary = _day_boundary(symbol, canonical, source)
    gaps = find_gaps(actual, first, window_end, canonical, boundary)
    duplicates = duplicate_open_times(actual)
    present = len(set(actual))
    expected_times = expected_open_times(first, window_end, canonical, boundary)
    return IntegrityReport(
        symbol=symbol,
        bar=canonical,
        start=first,
        end=last,
        expected=len(expected_times),
        present=present,
        missing=len(expected_times) - present,
        gaps=tuple(
            CandleGap(
                start=gap_start,
                end=gap_end,
                # 日线的期望网格不是均匀的（周末与休市日没有日线），只能数网格里的时刻。
                missing=sum(1 for moment in expected_times if gap_start <= moment < gap_end),
            )
            for gap_start, gap_end in gaps
        ),
        duplicates=tuple(duplicates),
        last_synced_at=last_synced_at,
    )


def _last_synced_at(symbol: str, bar: str, source: str | None) -> datetime | None:
    """该序列最近一次写入时刻；没有 K 线时返回 `None`，不拿当前时间冒充同步。"""

    statement = select(func.max(Candle.updated_at)).where(
        Candle.symbol == symbol, Candle.bar == bar
    )
    if source is not None:
        statement = statement.where(Candle.source == source)
    with session_scope() as session:
        latest = session.scalar(statement)
    return None if latest is None else from_epoch(int(latest))


def _day_boundary(symbol: str, bar: str, source: str | None) -> str:
    """这条序列按哪个市场的交易日排：代理行情按标的资产，OKX 行情按 UTC+8。

    日线网格只在处理日线时才需要，非日线周期传资产类别只是为了让签名统一。
    来源为空时取库里这一标的实际落过的来源：只有一种来源就按它的市场排；多种来源
    混存无法用一个网格同时对齐，退回标的自身的资产时段。
    """

    asset_type = _asset_type(symbol)
    if bar != "1d":
        return asset_type
    if source is not None:
        return day_asset_type(asset_type, source)

    available = candle_sources([symbol], bar).get(symbol, set())
    return day_asset_type(asset_type, next(iter(available)) if len(available) == 1 else None)


def _asset_type(symbol: str) -> str:
    """标的所属资产；表里没有这条标的时按未登记分类处理（临时取值同 `session`）。"""

    with session_scope() as session:
        asset_type = session.scalars(
            select(Instrument.asset_type).where(Instrument.symbol == symbol)
        ).first()
    return UNKNOWN_ASSET if asset_type is None else asset_type


def correlation(
    symbol_a: str,
    symbol_b: str,
    bar: str,
    *,
    method: str = "pearson",
    start: datetime | None = None,
    end: datetime | None = None,
    source: str | None = None,
) -> PairCorrelation:
    """两个标的同一周期的收盘价相关性：先按 open_time 取交集，再算系数。

    样本不足时系数为 `None`（不硬凑、不插值），样本数照实返回。
    """

    canonical = normalize_bar_or_raise(bar)
    if method not in METHODS:
        raise ValidationError(f"不支持的相关性方法 {method!r}; 支持: {', '.join(METHODS)}")
    if symbol_a == symbol_b:
        raise ValidationError("相关性需要两个不同的标的")

    left = {
        candle.open_time: float(candle.close)
        for candle in load_candles(symbol_a, canonical, start=start, end=end, source=source)
    }
    right = {
        candle.open_time: float(candle.close)
        for candle in load_candles(symbol_b, canonical, start=start, end=end, source=source)
    }
    common = sorted(left.keys() & right.keys())
    coefficient = correlate(
        [left[open_time] for open_time in common],
        [right[open_time] for open_time in common],
        method=method,
    )
    return PairCorrelation(
        symbol_a=symbol_a,
        symbol_b=symbol_b,
        bar=canonical,
        method=method,
        sample_size=len(common),
        coefficient=coefficient,
        p_value=None if coefficient is None else p_value(coefficient, len(common)),
    )


def save_snapshot(matrix: Matrix) -> int:
    """把一张矩阵按产品键写入快照表，返回写入的格子数（含对角线）。

    矩阵的标识是交易所标识（`symbol`），快照的标识是产品键（`product_key`）：关系
    分析与机会发现看的是产品，同一产品的现货与永续不该各算一条边。因此每个标的都要
    能在库里查到产品键，查不到就直接报错——不猜，也不把交易所标识塞进产品列。

    格子按产品键排序后入库，`(A, B)` 与 `(B, A)` 落在同一行；同一 `as_of` 重复保存
    走覆盖而不是追加，行数不变。同一产品的两种形态不能同时进同一张矩阵——它们会被
    折成同一个产品键，那等于把一个产品与自己的两种形态算成一条关系。
    """

    keys = _product_keys(matrix.symbols)
    rows: list[dict[str, object]] = []
    for index, symbol_a in enumerate(matrix.symbols):
        for symbol_b in matrix.symbols[index:]:
            key_a, key_b = keys[symbol_a], keys[symbol_b]
            if key_a == key_b and symbol_a != symbol_b:
                raise ValidationError(
                    f"标的 {symbol_a} 与 {symbol_b} 属于同一产品 {key_a}, 不能同时进相关矩阵"
                )
            product_a, product_b = sorted((key_a, key_b))
            rows.append(
                {
                    "product_key_a": product_a,
                    "product_key_b": product_b,
                    "bar": matrix.bar,
                    "window": matrix.window,
                    "as_of": to_epoch(matrix.as_of),
                    "coefficient": matrix[symbol_a][symbol_b],
                    "samples": matrix.sample_size(symbol_a, symbol_b),
                }
            )

    with session_scope() as session:
        for offset in range(0, len(rows), SNAPSHOT_BATCH_SIZE):
            statement = postgresql_insert(CorrelationSnapshot).values(
                rows[offset : offset + SNAPSHOT_BATCH_SIZE]
            )
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=["product_key_a", "product_key_b", "bar", "window", "as_of"],
                    set_={
                        "coefficient": statement.excluded.coefficient,
                        "samples": statement.excluded.samples,
                    },
                )
            )
    return len(rows)


def _product_keys(symbols: tuple[str, ...]) -> dict[str, str]:
    """交易所标识 → 产品键；库里没有的标的直接报错，不猜一个产品键出来。"""

    statement = select(Instrument.symbol, Instrument.product_key).where(
        Instrument.symbol.in_(symbols)
    )
    with session_scope() as session:
        known = {symbol: product_key for symbol, product_key in session.execute(statement)}
    missing = [symbol for symbol in symbols if symbol not in known]
    if missing:
        raise ValidationError(f"快照按产品键存储, 这些标的没有登记:{missing}")
    return {symbol: known[symbol] for symbol in symbols}


def load_snapshot(*, as_of: datetime, bar: str, window: int) -> Matrix | None:
    """读回某个时刻、某个周期的快照矩阵；没存过返回 `None`，不拿邻近时间凑。

    读回的矩阵以**产品键**标识（`matrix.symbols` 是产品键），行列按产品键排序，
    因此同一份库两次读出的顺序一致。对角线随快照一起存过，读回即原值。
    """

    if window < 1:
        raise ValidationError(f"快照的窗口必须是正整数:{window}")
    canonical = normalize_bar_or_raise(bar)
    if as_of.tzinfo is None:
        raise ValidationError("快照的 as_of 必须带时区")
    moment = to_epoch(as_of)
    statement = (
        select(CorrelationSnapshot)
        .where(
            CorrelationSnapshot.as_of == moment,
            CorrelationSnapshot.bar == canonical,
            CorrelationSnapshot.window == window,
        )
        .order_by(CorrelationSnapshot.product_key_a, CorrelationSnapshot.product_key_b)
    )
    with session_scope() as session:
        rows = list(session.scalars(statement))
    if not rows:
        return None

    ordered = tuple(
        sorted({row.product_key_a for row in rows} | {row.product_key_b for row in rows})
    )
    coefficients: dict[str, dict[str, float | None]] = {key: {} for key in ordered}
    samples: dict[tuple[str, str], int] = {}
    for row in rows:
        directions = (
            (row.product_key_a, row.product_key_b),
            (row.product_key_b, row.product_key_a),
        )
        for left, right in directions:
            coefficients[left][right] = row.coefficient
            samples[(left, right)] = row.samples
    return Matrix(
        symbols=ordered,
        bar=canonical,
        window=window,
        as_of=as_of,
        coefficients=coefficients,
        samples=samples,
    )


def current_bar(
    product_key: str,
    bar: str,
    *,
    inst_type: str,
    at: datetime | None = None,
) -> Bar | None:
    """按产品键取「当前有效行情」：一根带来源与资产时段的 K 线。

    来源不是常量，而是「资产时段 × 资产类别」的查表结果：代币化股票在美股交易时段
    读代理行情，休市时段读 OKX 合约行情；加密资产始终读 OKX 行情。所选来源在库里
    没有 K 线时返回 `None`——不用另一个来源的价格顶替，也不外推。

    `market_session` 描述的是这根 K 线自身的时段（按它的 `open_time` 判定），不是
    调用时刻的时段：一根凌晨取到的日线仍然属于它开盘时的那个时段。

    标的解析一律走 `app.instrument.resolve_instrument`：同一产品挂了多个报价时由它
    按「与永续同报价优先、其次 USDT」挑，本模块不再自己按 `symbol` 排序挑一行——
    两份规则迟早分叉，而 USDC 计价的现货被当成 USDT 那条会带出假价差。
    """

    canonical = normalize_bar_or_raise(bar)
    moment = datetime.now(tz=UTC) if at is None else at
    if moment.tzinfo is None:
        raise ValidationError("当前行情的判定时刻必须带时区")

    instrument = resolve_instrument(product_key, inst_type)
    session_state = asset_session(instrument.asset_type, moment, inst_type=instrument.inst_type)
    source = primary_source(session_state, instrument.asset_type, instrument.inst_type)

    statement = (
        select(Candle)
        .where(
            Candle.symbol == instrument.symbol,
            Candle.bar == canonical,
            Candle.source == source,
        )
        .order_by(Candle.open_time.desc())
        .limit(1)
    )
    with session_scope() as session:
        row = session.scalars(statement).first()
        loaded = None if row is None else row.to_bar()
    if loaded is None:
        return None
    return replace(
        loaded,
        market_session=asset_session(
            instrument.asset_type, loaded.open_time, inst_type=instrument.inst_type
        ),
    )


def market_overview(as_of: datetime | None, bar: str, inst_type: str) -> MarketOverview:
    """一个类别（`SPOT` / `SWAP`）在 `as_of` 时点的横截面总览。

    横截面只含该类别自己的可交易标的：两类标的的交易时段不同，混在一起数涨跌家数
    没有意义，因此 `inst_type` 必填、没有默认值。每个标的按「资产时段 × 资产类别」
    选来源（与 `current_bar` 同一条规则），代币化股票在美股交易时段读代理行情，
    加密资产与休市时段读 OKX 行情——同一个横截面里允许不同标的走不同来源，但每个
    标的只有一条自己此刻有效的序列。

    `as_of` 缺省取当前时刻；给出时必须带时区。它算在窗口内（`open_time` 精确到秒，
    上界取闭区间），之后的 K 线一根都不读。
    """

    canonical = normalize_bar_or_raise(bar)
    moment = datetime.now(tz=UTC) if as_of is None else as_of
    if moment.tzinfo is None:
        raise ValidationError("市场总览的 as_of 必须带时区")
    # K 线的 open_time 精确到秒，微秒在这里没有位置：截掉不改变任何一根是否落在窗口内，
    # 但能让响应里的 `as_of` 与库里的时刻同一精度。
    moment = moment.replace(microsecond=0)
    instruments = list_tradable(inst_type)
    bars_by_symbol = _recent_bars(instruments, canonical, moment, RESONANCE_WINDOW + 1)
    return MarketOverview(
        inst_type=inst_type,
        bar=canonical,
        as_of=moment,
        breadth=advance_decline(bars_by_symbol),
        resonance=resonance_strength(bars_by_symbol, RESONANCE_WINDOW),
    )


def _recent_bars(
    instruments: Sequence[Instrument],
    bar: str,
    as_of: datetime,
    count: int,
) -> dict[str, list[Bar]]:
    """每个标的在其有效来源下、`as_of`（含）之前最近 `count` 根 K 线。

    按 `(symbol, bar, open_time, source)` 主键倒序取固定条数，不整段读历史：横截面要
    的是窗口内的尾巴，读全量历史再把尾巴切掉只是把成本推到数据库。一个标的没有
    K 线就不进结果，广度与共振都按「至少有 2 根」筛参与标的，缺数据不会被算成不变。
    """

    moment = to_epoch(as_of)
    loaded: dict[str, list[Bar]] = {}
    with session_scope() as session:
        for instrument in instruments:
            session_state = asset_session(
                instrument.asset_type, as_of, inst_type=instrument.inst_type
            )
            source = primary_source(session_state, instrument.asset_type, instrument.inst_type)
            statement = (
                select(Candle)
                .where(
                    Candle.symbol == instrument.symbol,
                    Candle.bar == bar,
                    Candle.source == source,
                    Candle.open_time <= moment,
                )
                .order_by(Candle.open_time.desc())
                .limit(count)
            )
            rows = list(session.scalars(statement))
            if rows:
                loaded[instrument.symbol] = [row.to_bar() for row in reversed(rows)]
    return loaded
