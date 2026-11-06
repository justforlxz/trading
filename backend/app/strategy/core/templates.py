"""策略模板：把标的指标折算成非负信号强度（纯函数）。

每个模板是 `metrics -> TemplateSignal | None`。返回 `None` 表示「这组指标不足以
支持该模板」——调用方必须把它当作无依据而拒绝该腿，绝不能兜底成 0 分或伪造数值。
分数只用于同一策略内部的相对分配，不跨策略可比。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_EPS = 1e-9


@dataclass(frozen=True)
class TemplateSignal:
    """一个模板给出的一次判断：强度 + 用于生成 rationale 的具名指标。"""

    template: str
    score: float
    basis: dict[str, Any]


def _num(metrics: Mapping[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _basis(metrics: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: metrics[key] for key in keys if metrics.get(key) is not None}


def trend_following(metrics: Mapping[str, Any]) -> TemplateSignal | None:
    """趋势跟踪：20 日收益相对波动越大，趋势信号越强。"""

    ret_20d = _num(metrics, "ret_20d")
    if ret_20d is None:
        return None
    vol = _num(metrics, "vol_20d")
    denominator = max(abs(vol), _EPS) if vol is not None else 1.0
    return TemplateSignal(
        template="trend_following",
        score=abs(ret_20d) / denominator,
        basis=_basis(metrics, ("ret_20d", "vol_20d")),
    )


def momentum(metrics: Mapping[str, Any]) -> TemplateSignal | None:
    """动量：5 日收益即信号；波动只用于归一，缺失时按 1.0 处理。"""

    ret_5d = _num(metrics, "ret_5d")
    if ret_5d is None:
        return None
    vol = _num(metrics, "vol_20d")
    denominator = max(abs(vol), _EPS) if vol is not None else 1.0
    return TemplateSignal(
        template="momentum",
        score=abs(ret_5d) / denominator,
        basis=_basis(metrics, ("ret_5d", "vol_20d")),
    )


def _correlation(metrics: Mapping[str, Any]) -> tuple[float | None, str | None]:
    """优先取关系边系数；机会配对只给 correlation，同口径回退并保留原名进依据。"""

    coefficient = _num(metrics, "coefficient")
    if coefficient is not None:
        return coefficient, "coefficient"
    correlation = _num(metrics, "correlation")
    if correlation is not None:
        return correlation, "correlation"
    return None, None


def correlation(metrics: Mapping[str, Any]) -> TemplateSignal | None:
    """相关性：强相关 + 稳定滞后关系才值得配对。"""

    coefficient, key = _correlation(metrics)
    if coefficient is None or key is None:
        return None
    stability = _num(metrics, "stability")
    return TemplateSignal(
        template="correlation",
        score=abs(coefficient) * (1.0 if stability is None else max(stability, 0.0)),
        basis=_basis(metrics, (key, "best_lag", "stability")),
    )


def mean_reversion(metrics: Mapping[str, Any]) -> TemplateSignal | None:
    """均值回归：价差偏离 z 越大，回归空间越大。"""

    spread_z = _num(metrics, "spread_z")
    if spread_z is None:
        return None
    return TemplateSignal(
        template="mean_reversion",
        score=abs(spread_z),
        basis=_basis(metrics, ("spread_z", "correlation", "overlap_bars")),
    )


def relative_strength(metrics: Mapping[str, Any]) -> TemplateSignal | None:
    """相对强弱：`rs_ratio` 偏离 1 与动量变化共同决定信号。"""

    rs_ratio = _num(metrics, "rs_ratio")
    rs_momentum = _num(metrics, "rs_momentum")
    if rs_ratio is None and rs_momentum is None:
        return None
    score = abs((rs_ratio if rs_ratio is not None else 1.0) - 1.0) + abs(rs_momentum or 0.0)
    return TemplateSignal(
        template="relative_strength",
        score=score,
        basis=_basis(metrics, ("rs_ratio", "rs_momentum")),
    )


def long_short(metrics: Mapping[str, Any]) -> TemplateSignal | None:
    """多空组合：高相关叠加收益差，才构成可交易的多空对。"""

    coefficient, key = _correlation(metrics)
    ret_5d = _num(metrics, "ret_5d")
    if coefficient is None or key is None or ret_5d is None:
        return None
    peer = _num(metrics, "peer_ret_5d")
    spread = abs(ret_5d - peer) if peer is not None else abs(ret_5d)
    return TemplateSignal(
        template="long_short",
        score=abs(coefficient) * (1.0 + spread),
        basis=_basis(metrics, (key, "ret_5d", "peer_ret_5d")),
    )


TEMPLATES: dict[str, Callable[[Mapping[str, Any]], TemplateSignal | None]] = {
    "trend_following": trend_following,
    "momentum": momentum,
    "correlation": correlation,
    "mean_reversion": mean_reversion,
    "relative_strength": relative_strength,
    "long_short": long_short,
}

TEMPLATE_NAMES: tuple[str, ...] = tuple(TEMPLATES)

# 策略种类名可以当作模板组使用：它们展开成一组具体模板，分数由组内最高者决定。
# 模板名本身仍是单一口径，组名只是入口别名，不改任何指标计算。
TEMPLATE_ALIASES: dict[str, tuple[str, ...]] = {
    "relative_value": ("correlation", "mean_reversion", "relative_strength", "long_short"),
    "directional": ("trend_following", "momentum", "correlation"),
}

KNOWN_TEMPLATES: tuple[str, ...] = (*TEMPLATE_NAMES, *TEMPLATE_ALIASES)


def expand_templates(names: Sequence[str]) -> tuple[str, ...]:
    """把模板组名展开成具体模板，保留首次出现顺序并按去重后的顺序求值。"""

    expanded: list[str] = []
    for name in names:
        for template in TEMPLATE_ALIASES.get(name, (name,)):
            if template not in expanded:
                expanded.append(template)
    return tuple(expanded)


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def format_rationale(basis: Mapping[str, Any], *, window_bars: int | None, template: str) -> str:
    """把「指标名=数值」与数据窗口拼成可复核的依据；空 basis 视为错误。"""

    parts = [f"{key}={_fmt(value)}" for key, value in basis.items() if value is not None]
    if not parts:
        raise ValueError(f"template {template} produced no metric basis")
    if window_bars is not None:
        parts.append(f"window={window_bars}")
    return f"{template}: " + " / ".join(parts)


__all__ = [
    "KNOWN_TEMPLATES",
    "TEMPLATES",
    "TEMPLATE_ALIASES",
    "TEMPLATE_NAMES",
    "TemplateSignal",
    "correlation",
    "expand_templates",
    "format_rationale",
    "long_short",
    "mean_reversion",
    "momentum",
    "relative_strength",
    "trend_following",
]
