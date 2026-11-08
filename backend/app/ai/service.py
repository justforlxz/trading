"""助手编排层: 走只读端口取事实 -> 组织引用 -> 可选模型改写 -> 写审计。

约束:
- 只经 `app.ports.ai_reads` 读域数据, 不 import 任何业务域模块;
- 判定顺序固定: 动作安全检查 -> 正向读取许可 -> 域端口调用; 前两步不通过时端口
  调用次数必须为 0;
- 所有 `/ai/*` 200 响应带 `read_only=true` 与 `answerable`; 拒答响应不带任何域数据;
- 每次成功或被拒绝的调用都写一条 `ops.audit_log` (actor='ai'), 这是唯一允许的写入。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai import audit
from app.ai.adapter import UpstreamFailure, build_adapter
from app.ai.config import (
    PROVIDER_RULE_BASED,
    RULE_MODEL,
    AiConfig,
    load_config,
)
from app.ai.core import explain, glossary, strategy_review, suggest
from app.ai.core import query as query_core
from app.ai.core.citations import citation
from app.ai.core.prompts import SYSTEM_PROMPT, facts_block
from app.ai.errors import (
    AI_INVALID_REQUEST,
    AI_UPSTREAM_ERROR,
    AI_WRITE_FORBIDDEN,
    AiError,
    from_reads_error,
    not_configured,
)
from app.config import get_settings
from app.db.session import AsyncSession
from app.ports.ai_reads import AiReads, AiReadsError

logger = logging.getLogger(__name__)

MAX_QUERY_LIMIT = 50
DEFAULT_QUERY_LIMIT = 10
READ_ONLY = True

# 数据不足时统一给一个缺失项名, 避免把域内部字段名泄露到响应里。
MISSING_DOMAIN_DATA = "domain_data"


@dataclass(slots=True)
class Facts:
    summary: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    guard_no_growth: bool = False


# --------------------------------------------------------------------------- #
# 市场与关系
# --------------------------------------------------------------------------- #


async def _facts_market(
    reads: AiReads,
    *,
    as_of: datetime | None,
    bar: str | None,
    scope: str | None,
) -> Facts:
    settings = get_settings()
    normalized = bar or settings.research_bar
    moment = as_of or datetime.now(UTC)
    span_days = 30 if normalized == "1d" else 3
    start = moment - timedelta(days=span_days)

    # 只读既有日历; 不调用 sync_sessions, 不为满足查询而写入。
    sessions = await reads.market_sessions(start=start.date(), end=moment.date())
    payload = await reads.market_coverage(
        inst_ids=_scope_ids(scope),
        bar=normalized,
        start=start,
        end=moment,
    )
    coverage = list(payload.get("coverage") or [])
    target_count = len(payload.get("instruments") or [])
    citations = explain.market_citations(
        sessions=sessions,
        coverage=coverage,
        target_count=target_count,
    )
    summary = explain.market_summary(
        sessions=sessions,
        coverage=coverage,
        target_count=target_count,
        bar=normalized,
    )
    missing = [] if coverage else ["market_coverage"]
    return Facts(
        summary=summary,
        citations=citations,
        missing=missing,
        extra={"as_of": moment.isoformat(), "bar": normalized},
    )


async def _facts_relations(
    reads: AiReads,
    *,
    target_id: int,
    window_bars: int | None,
    method: str | None,
    price_basis: str | None,
    max_items: int,
) -> Facts:
    payload = await reads.target_relations(target_id=target_id)
    snapshot = payload.get("snapshot")
    if not snapshot:
        return Facts(
            summary=f"数据不足: 目标 {target_id} 尚未计算关系快照。缺失项: relations_snapshot",
            missing=["relations_snapshot"],
            extra={"target_id": target_id},
        )
    mismatched = [
        name
        for name, wanted, actual in (
            ("window_bars", window_bars, snapshot.get("window_bars")),
            ("method", method, snapshot.get("method")),
            ("price_basis", price_basis, snapshot.get("price_basis")),
        )
        if wanted is not None and wanted != actual
    ]
    if mismatched:
        return Facts(
            summary=(
                f"数据不足: 目标 {target_id} 最新快照与筛选条件不一致 ({', '.join(mismatched)}) 。"
                "缺失项: snapshot_matching_filters"
            ),
            missing=["snapshot_matching_filters"],
            extra={"target_id": target_id, "mismatched": mismatched},
        )
    edges = list(payload.get("edges") or [])
    citations = explain.relations_citations(
        target_id=target_id,
        snapshot=snapshot,
        edges=edges,
        max_items=max_items,
    )
    summary = explain.relations_summary(
        target_id=target_id,
        snapshot=snapshot,
        edges=edges,
        significant_changes=len(payload.get("significant_changes") or []),
    )
    return Facts(
        summary=summary,
        citations=citations,
        missing=[] if edges else ["relation_edges"],
        extra={"target_id": target_id, "status": payload.get("status")},
    )


# --------------------------------------------------------------------------- #
# 策略与回测
# --------------------------------------------------------------------------- #


async def _facts_strategy(reads: AiReads, *, strategy_id: int, max_items: int) -> Facts:
    detail = await reads.strategy_detail(strategy_id=strategy_id)
    view = detail["strategy"]
    leg_views = list(detail["legs"])[:max_items]
    citations = strategy_review.strategy_citations(strategy=view, legs=leg_views)
    summary = strategy_review.strategy_summary(
        strategy=view, legs=leg_views, approval_count=detail["approval_count"]
    )
    return Facts(
        summary=summary,
        citations=citations,
        missing=[] if leg_views else ["strategy_legs"],
        extra={"strategy_id": strategy_id},
    )


async def _facts_backtest(reads: AiReads, *, run_id: int, max_items: int) -> Facts:
    detail = await reads.backtest_detail(run_id=run_id)
    run_view = detail["run"]
    metric_views = list(detail["metrics"])[:max_items]
    citations = strategy_review.backtest_citations(run=run_view, metrics=metric_views)
    summary = strategy_review.backtest_summary(run=run_view, metrics=metric_views)
    return Facts(
        summary=summary,
        citations=citations,
        missing=[] if metric_views else ["backtest_metrics"],
        extra={"run_id": run_id},
        guard_no_growth=True,
    )


# --------------------------------------------------------------------------- #
# 风控与持仓 (只读问答用)
# --------------------------------------------------------------------------- #


async def _facts_risk(reads: AiReads, *, strategy_id: int | None) -> Facts:
    payload = await reads.risk_status(strategy_id=strategy_id)
    breaches = payload.get("breaches") or []
    summary = (
        f"风控状态: allowed={payload.get('allowed')}, reason={payload.get('reason')}, "
        f"杠杆 {payload.get('leverage')}, 集中度 {payload.get('concentration')}, "
        f"总敞口 {payload.get('gross_exposure')}, 净敞口 {payload.get('net_exposure')}, "
        f"违反项 {len(breaches)} 条。"
    )
    citations = [
        citation(
            "risk_status",
            "GET /api/v1/risk/status",
            scope=payload.get("scope"),
            strategy_id=payload.get("strategy_id"),
            policy_version=payload.get("policy_version"),
            allowed=payload.get("allowed"),
            reason=payload.get("reason"),
            leverage=payload.get("leverage"),
            concentration=payload.get("concentration"),
            gross_exposure=payload.get("gross_exposure"),
            net_exposure=payload.get("net_exposure"),
            breaches=breaches,
        )
    ]
    return Facts(summary=summary, citations=citations, extra={"strategy_id": strategy_id})


async def _facts_positions(reads: AiReads, *, limit: int) -> Facts:
    payload = await reads.positions()
    items = list(payload.get("items") or [])[:limit]
    totals = payload.get("totals") or {}
    summary = (
        f"当前持仓 {len(items)} 条 (展示上限 {limit}) ; "
        f"合计已实现盈亏 {totals.get('realized_pnl')}, "
        f"未实现盈亏 {totals.get('unrealized_pnl')}, "
        f"总盈亏 {totals.get('total_pnl')}, "
        f"毛名义 {totals.get('gross_notional')}, 净名义 {totals.get('net_notional')}。"
    )
    citations = [
        citation(
            "position",
            "GET /api/v1/execution/positions",
            strategy_id=item.get("strategy_id"),
            instrument_id=item.get("instrument_id"),
            inst_id=item.get("inst_id"),
            position_side=item.get("position_side"),
            quantity=item.get("quantity"),
            unrealized_pnl=item.get("unrealized_pnl"),
            notional=item.get("notional"),
        )
        for item in items
    ]
    return Facts(
        summary=summary,
        citations=citations,
        missing=[] if items else ["positions"],
        extra={"limit": limit},
    )


async def _facts_concept(term: str) -> Facts:
    definition = glossary.definition_of(term)
    if definition is None:
        return Facts(
            summary="术语表未收录该概念。缺失项: glossary",
            missing=["glossary"],
        )
    citations = [
        citation("glossary", f"glossary#{term}", term=term, definition=definition),
    ]
    return Facts(summary=f"{term}: {definition}", citations=citations, extra={"term": term})


# --------------------------------------------------------------------------- #
# 渲染与审计
# --------------------------------------------------------------------------- #


def _model_view(config: AiConfig, *, degraded: bool) -> dict[str, str]:
    if degraded:
        return {"provider": PROVIDER_RULE_BASED, "model": RULE_MODEL}
    return config.model_view()


async def _render(
    config: AiConfig,
    facts: Facts,
    *,
    answer_key: str,
) -> tuple[dict[str, Any], int | None]:
    adapter = build_adapter(config)
    if adapter is None:
        raise not_configured()
    degraded = config.rule_based
    tokens: int | None = None
    text = facts.summary
    if not config.rule_based:
        prompt = f"{facts_block(facts.citations)}\n\n请基于上述事实回答: {facts.summary}"
        try:
            result = await adapter.complete(system=SYSTEM_PROMPT, prompt=prompt)
            text = result.text
            tokens = result.tokens
        except UpstreamFailure as exc:
            if not config.fallback_enabled:
                raise AiError(
                    AI_UPSTREAM_ERROR,
                    f"模型服务不可用: {exc}",
                    status_code=502,
                ) from exc
            logger.warning("ai upstream failed, falling back to rules: %s", exc)
            degraded = True
    if facts.guard_no_growth and strategy_review.has_growth_advice(text):
        # 亏损回测不允许出现加仓/扩大仓位类结论: 丢弃模型文本, 回退确定性摘要。
        text = facts.summary
        degraded = True
    payload: dict[str, Any] = {
        answer_key: text,
        "citations": facts.citations,
        "model": _model_view(config, degraded=degraded),
        "degraded": degraded,
        "read_only": READ_ONLY,
        "answerable": True,
        **facts.extra,
    }
    if facts.missing:
        payload["missing"] = facts.missing
    return payload, tokens


def _audit_outcome(exc: AiError) -> str:
    if exc.status_code == 403:
        return audit.OUTCOME_FORBIDDEN
    if exc.status_code == 404:
        return audit.OUTCOME_NOT_FOUND
    return audit.OUTCOME_ERROR


def _insufficient(exc: AiReadsError) -> Facts:
    """端口 `no_data` -> 200 数据不足, 不编造数值。"""

    return Facts(summary=f"数据不足: {exc.message}", missing=[MISSING_DOMAIN_DATA])


async def _run(
    session: AsyncSession,
    reads: AiReads,
    *,
    request_id: str | None,
    action: str,
    resource: str,
    resource_id: str | int | None,
    builder: Callable[[AiConfig], Awaitable[Facts]],
    answer_key: str = "summary",
) -> dict[str, Any]:
    config = load_config(get_settings())
    if not config.available:
        raise not_configured()
    started = time.perf_counter()
    try:
        try:
            facts = await builder(config)
        except AiReadsError as exc:
            if exc.reason != "no_data":
                raise
            facts = _insufficient(exc)
        payload, tokens = await _render(config, facts, answer_key=answer_key)
    except AiReadsError as exc:
        error = from_reads_error(exc)
        await audit.record(
            session,
            request_id=request_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            model=config.model_view(),
            latency_ms=_elapsed_ms(started),
            outcome=_audit_outcome(error),
        )
        raise error from exc
    except AiError as exc:
        await audit.record(
            session,
            request_id=request_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            model=config.model_view(),
            latency_ms=_elapsed_ms(started),
            outcome=_audit_outcome(exc),
        )
        raise
    await audit.record(
        session,
        request_id=request_id,
        action=action,
        resource=resource,
        resource_id=resource_id,
        model=payload.get("model") or config.model_view(),
        latency_ms=_elapsed_ms(started),
        outcome=audit.OUTCOME_OK,
        tokens=tokens,
    )
    return payload


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #


async def explain_market(
    session: AsyncSession,
    reads: AiReads,
    *,
    request_id: str | None,
    as_of: datetime | None = None,
    bar: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    return await _run(
        session,
        reads,
        request_id=request_id,
        action="ai.explain.market",
        resource="market",
        resource_id=None,
        builder=lambda config: _facts_market(reads, as_of=as_of, bar=bar, scope=scope),
    )


async def explain_relations(
    session: AsyncSession,
    reads: AiReads,
    *,
    request_id: str | None,
    target_id: int,
    window_bars: int | None = None,
    method: str | None = None,
    price_basis: str | None = None,
) -> dict[str, Any]:
    return await _run(
        session,
        reads,
        request_id=request_id,
        action="ai.explain.relations",
        resource="target",
        resource_id=target_id,
        builder=lambda cfg: _facts_relations(
            reads,
            target_id=target_id,
            window_bars=window_bars,
            method=method,
            price_basis=price_basis,
            max_items=min(cfg.max_citations, 50),
        ),
    )


async def explain_strategy(
    session: AsyncSession,
    reads: AiReads,
    *,
    request_id: str | None,
    strategy_id: int,
) -> dict[str, Any]:
    return await _run(
        session,
        reads,
        request_id=request_id,
        action="ai.explain.strategy",
        resource="strategy",
        resource_id=strategy_id,
        builder=lambda cfg: _facts_strategy(
            reads, strategy_id=strategy_id, max_items=max(cfg.max_citations, 1)
        ),
    )


async def explain_backtest(
    session: AsyncSession,
    reads: AiReads,
    *,
    request_id: str | None,
    run_id: int,
) -> dict[str, Any]:
    return await _run(
        session,
        reads,
        request_id=request_id,
        action="ai.explain.backtest",
        resource="backtest",
        resource_id=run_id,
        # 10 项指标必须全量引用, 不受 max_citations 截断。
        builder=lambda cfg: _facts_backtest(reads, run_id=run_id, max_items=100),
    )


async def query(
    session: AsyncSession,
    reads: AiReads,
    *,
    request_id: str | None,
    question: str,
    limit: int | None = None,
) -> dict[str, Any]:
    text = question.strip()
    if not text:
        raise AiError(AI_INVALID_REQUEST, "问题不能为空", status_code=422)
    if len(text) > 2000:
        raise AiError(
            AI_INVALID_REQUEST,
            "问题过长: 最多 2000 个字符",
            status_code=422,
            details={"field": "question", "max_length": 2000},
        )
    bounded_limit = _bounded_limit(limit)
    config = load_config(get_settings())
    if not config.available:
        raise not_configured()

    started = time.perf_counter()
    decision = query_core.assess(text)

    if decision.refusal == query_core.REFUSAL_WRITE:
        message = query_core.REFUSAL_MESSAGES[query_core.REFUSAL_WRITE]
        await audit.record(
            session,
            request_id=request_id,
            action="ai.query",
            resource="query",
            resource_id=None,
            model=config.model_view(),
            latency_ms=_elapsed_ms(started),
            outcome=audit.OUTCOME_FORBIDDEN,
        )
        raise AiError(
            AI_WRITE_FORBIDDEN,
            message,
            status_code=403,
            details={
                "refusal": {
                    "code": decision.refusal,
                    "message": message,
                    "matched_object_class": decision.matched,
                }
            },
        )

    if not decision.answerable:
        # 未许可 / 未识别: 在调用任何读端口之前返回, citations 必为空。
        # 审计用 refused 与真正的写意图拒绝区分, 便于事后核对。
        await audit.record(
            session,
            request_id=request_id,
            action="ai.query",
            resource="query",
            resource_id=None,
            model=config.model_view(),
            latency_ms=_elapsed_ms(started),
            outcome=audit.OUTCOME_REFUSED,
        )
        return _refusal_payload(config, decision)

    try:
        facts = await _query_facts(
            reads, question=text, intent=decision.intent or "", limit=bounded_limit
        )
        payload, tokens = await _render(config, facts, answer_key="answer")
    except AiError as exc:
        await audit.record(
            session,
            request_id=request_id,
            action="ai.query",
            resource="query",
            resource_id=None,
            model=config.model_view(),
            latency_ms=_elapsed_ms(started),
            outcome=_audit_outcome(exc),
        )
        raise
    payload["intent"] = decision.intent
    await audit.record(
        session,
        request_id=request_id,
        action="ai.query",
        resource="query",
        resource_id=None,
        model=payload.get("model") or config.model_view(),
        latency_ms=_elapsed_ms(started),
        outcome=audit.OUTCOME_OK,
        tokens=tokens,
    )
    return payload


def _refusal_payload(config: AiConfig, decision: query_core.Decision) -> dict[str, Any]:
    """200 拒答: 固定文案 + reason, 不含任何域数据与引用。"""

    return {
        "answer": query_core.REFUSAL_MESSAGES.get(decision.refusal or "", "无法据此作答。"),
        "intent": None,
        "answerable": False,
        "read_only": READ_ONLY,
        "reason": decision.refusal,
        "citations": [],
        "model": _model_view(config, degraded=True),
        "degraded": True,
    }


async def _query_facts(
    reads: AiReads,
    *,
    question: str,
    intent: str,
    limit: int,
) -> Facts:
    config = load_config(get_settings())
    try:
        return await _dispatch(reads, config=config, question=question, intent=intent, limit=limit)
    except AiReadsError as exc:
        if exc.reason == "no_data":
            return _insufficient(exc)
        raise from_reads_error(exc) from exc


async def _dispatch(
    reads: AiReads,
    *,
    config: AiConfig,
    question: str,
    intent: str,
    limit: int,
) -> Facts:
    if intent == query_core.INTENT_MARKET:
        return await _facts_market(reads, as_of=None, bar=None, scope=None)
    if intent == query_core.INTENT_RELATIONS:
        target_id = query_core.extract_entity_id(question, intent)
        if target_id is None:
            return await _target_list_facts(reads)
        return await _facts_relations(
            reads,
            target_id=target_id,
            window_bars=None,
            method=None,
            price_basis=None,
            max_items=config.max_citations,
        )
    if intent == query_core.INTENT_STRATEGY:
        strategy_id = query_core.extract_entity_id(question, intent)
        if strategy_id is None:
            return await _strategy_list_facts(reads, limit=limit)
        return await _facts_strategy(
            reads, strategy_id=strategy_id, max_items=max(config.max_citations, 1)
        )
    if intent == query_core.INTENT_BACKTEST:
        run_id = query_core.extract_entity_id(question, intent)
        if run_id is None:
            return Facts(
                summary=("数据不足: 请提供回测 id (例如 “解释回测 1”) 。缺失项: run_id"),
                missing=["run_id"],
            )
        return await _facts_backtest(reads, run_id=run_id, max_items=100)
    if intent == query_core.INTENT_RISK:
        return await _facts_risk(reads, strategy_id=query_core.extract_entity_id(question, intent))
    if intent == query_core.INTENT_POSITIONS:
        return await _facts_positions(reads, limit=limit)
    if intent == query_core.INTENT_CONCEPT:
        term = glossary.resolve_term(query_core.normalize_question(question))
        return await _facts_concept(term or "")
    raise AiError(AI_INVALID_REQUEST, "未支持的只读意图", status_code=422)


async def _target_list_facts(reads: AiReads) -> Facts:
    targets = await reads.target_list(limit=20)
    if not targets:
        return Facts(summary="数据不足: 尚未添加目标股票。缺失项: targets", missing=["targets"])
    summary = (
        "当前目标股票: "
        + ", ".join(f"{target['id']}:{target['symbol']}" for target in targets)
        + "。请指明目标 id 后我再解释其关系。"
    )
    citations = [
        citation(
            "target",
            "GET /api/v1/targets",
            target_id=target["id"],
            symbol=target["symbol"],
            instrument_id=target["instrument_id"],
            enabled=target["enabled"],
        )
        for target in targets
    ]
    return Facts(summary=summary, citations=citations, extra={})


async def _strategy_list_facts(reads: AiReads, *, limit: int) -> Facts:
    rows = await reads.strategy_list(limit=limit)
    if not rows:
        return Facts(summary="数据不足: 尚无策略。缺失项: strategies", missing=["strategies"])
    summary = (
        "当前策略: "
        + ", ".join(f"{row['id']}:{row['name']}({row['status']})" for row in rows)
        + "。请指明策略 id 后我再解读。"
    )
    citations = [
        citation(
            "strategy",
            f"GET /api/v1/strategies/{row['id']}",
            strategy_id=row["id"],
            version=row["version"],
            status=row["status"],
            kind=row["kind"],
        )
        for row in rows
    ]
    return Facts(summary=summary, citations=citations, extra={})


def _bounded_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_QUERY_LIMIT
    return max(1, min(limit, MAX_QUERY_LIMIT))


def _scope_ids(scope: str | None) -> list[str] | None:
    if not scope:
        return None
    inst_ids = [item.strip() for item in scope.split(",") if item.strip()]
    return inst_ids or None


# --------------------------------------------------------------------------- #
# 策略草案建议 (不落库)
# --------------------------------------------------------------------------- #


async def suggest_strategy(
    session: AsyncSession,
    reads: AiReads,
    *,
    request_id: str | None,
    opportunity_id: int | None = None,
    target_id: int | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if opportunity_id is None and target_id is None:
        raise AiError(
            AI_INVALID_REQUEST,
            "需要提供 target_id 或 opportunity_id",
            status_code=422,
        )
    resource = "target" if target_id is not None else "opportunity"
    resource_id = target_id if target_id is not None else opportunity_id
    return await _run(
        session,
        reads,
        request_id=request_id,
        action="ai.suggest.strategy",
        resource=resource,
        resource_id=resource_id,
        builder=lambda cfg: _suggest_facts(
            reads,
            opportunity_id=opportunity_id,
            target_id=target_id,
            params=params or {},
            max_items=cfg.max_citations,
        ),
        answer_key="summary",
    )


async def _suggest_facts(
    reads: AiReads,
    *,
    opportunity_id: int | None,
    target_id: int | None,
    params: dict[str, Any],
    max_items: int,
) -> Facts:
    draft_params = {"source": "ai_suggestion", **params}
    if target_id is not None:
        payload = await reads.target_relations(target_id=target_id)
        snapshot = payload.get("snapshot")
        if not snapshot:
            return _draft_facts(
                legs=[],
                citations=[],
                summary=(
                    f"数据不足: 目标 {target_id} 尚未计算关系快照。缺失项: relations_snapshot"
                ),
                missing=["relations_snapshot"],
                params=draft_params,
            )
        edges = list(payload.get("edges") or [])
        enriched = [
            {
                "instrument_id": edge.get("instrument_id"),
                "inst_id": edge.get("counterparty_inst_id"),
                "coefficient": edge.get("coefficient"),
                "best_lag": edge.get("best_lag"),
            }
            for edge in edges
        ]
        legs = suggest.build_legs(enriched, max_weight=1.0)
        citations = explain.relations_citations(
            target_id=target_id,
            snapshot=snapshot,
            edges=edges,
            max_items=max_items,
        )
        summary = suggest.suggest_summary(target_id=target_id, legs=legs)
        missing = [] if legs else ["relation_edges"]
        return _draft_facts(
            legs=legs,
            citations=citations,
            summary=summary,
            missing=missing,
            params=draft_params,
        )

    opportunity = await reads.opportunity_detail(opportunity_id=opportunity_id or 0)
    side = "long" if str(opportunity["direction"]).lower() in {"long", "up", "buy"} else "short"
    reasons = opportunity.get("reasons") or []
    rationale = reasons[0] if reasons else "机会发现结果"
    legs = [
        {
            "instrument_id": opportunity["instrument_id"],
            "inst_id": opportunity["inst_id"],
            "side": side,
            "target_weight": "0.50",
            "rationale": str(rationale),
        }
    ]
    citations = [
        citation(
            "opportunity",
            f"GET /api/v1/opportunities/{opportunity['id']}",
            opportunity_id=opportunity["id"],
            kind=opportunity["kind"],
            direction=opportunity["direction"],
            score=str(opportunity["score"]),
            instrument_id=opportunity["instrument_id"],
            inst_id=opportunity["inst_id"],
        )
    ]
    return _draft_facts(
        legs=legs,
        citations=citations,
        summary=(
            f"基于机会 {opportunity['id']} ({opportunity['kind']}/{opportunity['direction']}) "
            f"生成单腿草案 (未落库) : {side} {opportunity['inst_id']} 权重 0.50。"
        ),
        missing=[],
        params=draft_params,
    )


def _draft_facts(
    *,
    legs: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    summary: str,
    missing: list[str],
    params: dict[str, Any],
) -> Facts:
    return Facts(
        summary=summary,
        citations=citations,
        missing=missing,
        extra={
            "draft_only": True,
            "persisted": False,
            "strategy": {
                "kind": "relative_value" if len(legs) > 1 else "directional",
                "templates": ["correlation", "relative_strength"],
                "params": params,
            },
            "legs": legs,
            "warnings": suggest.warnings_for(legs),
        },
    )


__all__ = [
    "explain_backtest",
    "explain_market",
    "explain_relations",
    "explain_strategy",
    "query",
    "suggest_strategy",
]
