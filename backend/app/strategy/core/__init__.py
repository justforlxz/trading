"""策略核心计算（纯函数）：模板打分、权重分配、约束校验与内容指纹。"""

from app.strategy.core.builder import BuiltLeg, LegCandidate, allocate, build_legs, select_signal
from app.strategy.core.constraints import (
    ConstraintViolation,
    check_legs,
    gross_exposure,
    net_exposure,
)
from app.strategy.core.hash import content_hash, strategy_key
from app.strategy.core.templates import TEMPLATES, TemplateSignal, expand_templates

__all__ = [
    "TEMPLATES",
    "BuiltLeg",
    "ConstraintViolation",
    "LegCandidate",
    "TemplateSignal",
    "allocate",
    "build_legs",
    "check_legs",
    "content_hash",
    "expand_templates",
    "gross_exposure",
    "net_exposure",
    "select_signal",
    "strategy_key",
]
