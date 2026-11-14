"""策略域：目标组合、只读行情视图、组件/模板/策略协议、注册表与参数校验。

本域对外只发布一种交易目标：`TargetPortfolio`（多腿、方向、目标权重）。策略只产出
权重，组合生成 `build_target` 把权重归一化并比对约束，`target_quantity` 再把一条腿
换成按类别换算出的数量。策略不产出单标的的动作序列，也不接触交易所、账户与会话。

拓扑是「六个组件 + 两类模板」：组件各自回答「这个标的偏多还是偏空、强度多少」，
模板决定用哪些组件、怎么配权、组合成什么形态。旧的单指标策略保留为组件的用例，
登记在策略表里，不是组合模板。

跨包调用一律走本门面，不允许 `from app.strategy.target import ...` 之类的子模块直连。
"""

from app.strategy.approval import (
    DRAFT,
    LIFECYCLE_STAGES,
    REJECTED,
    TRANSITIONS,
    ApprovalTransition,
    ValidationGate,
    ValidationReport,
    advance,
    check_transition,
    latest_transition,
    list_transitions,
)
from app.strategy.builtin import BollingerReversion, MacdMomentum, MaCross, RsiReversal
from app.strategy.components import (
    Breadth,
    CorrelationShift,
    MeanReversion,
    Momentum,
    RelativeStrength,
    Trend,
)
from app.strategy.constraints import PortfolioConstraints, check_constraints
from app.strategy.management import (
    InstrumentStrategyRecord,
    StrategyRecord,
    StrategyVersionRecord,
    create_strategy,
    create_version,
    get_user_strategy,
    get_version,
    link_backtest,
    list_strategies_for_instrument,
    list_user_strategies,
    list_versions,
    replace_version_instruments,
    update_strategy,
)
from app.strategy.model import (
    StrategyApprovalRow,
    StrategyInstanceRow,
    StrategyInstrumentRow,
    StrategyLinkedBacktestRow,
    StrategyReplayRow,
    StrategyTemplateRow,
    StrategyVersionRow,
    UserStrategyRow,
)
from app.strategy.params import resolve_params
from app.strategy.protocol import (
    Component,
    ComponentSignal,
    Requirements,
    Strategy,
    StrategyMeta,
    Template,
)
from app.strategy.registry import (
    get_component,
    get_strategy,
    get_template,
    list_components,
    list_strategies,
    list_templates,
    register_component,
    register_strategy,
    register_template,
)
from app.strategy.service import (
    InstanceRecord,
    StrategySummary,
    create_instance,
    delete_instance,
    evaluate_replay,
    get_instance,
    list_instances,
    list_replays,
    prepare_replay,
    save_replay,
    summarize_instances,
    update_instance,
)
from app.strategy.target import (
    TargetLeg,
    TargetPortfolio,
    TargetQuantity,
    build_target,
    normalize_weights,
    target_quantity,
)
from app.strategy.templates import Directional, RelativeValue
from app.strategy.view import MarketView

__all__ = [
    "DRAFT",
    "LIFECYCLE_STAGES",
    "REJECTED",
    "TRANSITIONS",
    "ApprovalTransition",
    "BollingerReversion",
    "Breadth",
    "Component",
    "ComponentSignal",
    "CorrelationShift",
    "Directional",
    "InstanceRecord",
    "InstrumentStrategyRecord",
    "MaCross",
    "MacdMomentum",
    "MarketView",
    "MeanReversion",
    "Momentum",
    "PortfolioConstraints",
    "RelativeStrength",
    "RelativeValue",
    "Requirements",
    "RsiReversal",
    "Strategy",
    "StrategyApprovalRow",
    "StrategyInstanceRow",
    "StrategyInstrumentRow",
    "StrategyLinkedBacktestRow",
    "StrategyMeta",
    "StrategyRecord",
    "StrategyReplayRow",
    "StrategySummary",
    "StrategyTemplateRow",
    "StrategyVersionRecord",
    "StrategyVersionRow",
    "TargetLeg",
    "TargetPortfolio",
    "TargetQuantity",
    "Template",
    "Trend",
    "UserStrategyRow",
    "ValidationGate",
    "ValidationReport",
    "advance",
    "build_target",
    "check_constraints",
    "check_transition",
    "create_instance",
    "create_strategy",
    "create_version",
    "delete_instance",
    "evaluate_replay",
    "get_component",
    "get_instance",
    "get_strategy",
    "get_template",
    "get_user_strategy",
    "get_version",
    "latest_transition",
    "link_backtest",
    "list_components",
    "list_instances",
    "list_replays",
    "list_strategies",
    "list_strategies_for_instrument",
    "list_templates",
    "list_transitions",
    "list_user_strategies",
    "list_versions",
    "normalize_weights",
    "prepare_replay",
    "register_component",
    "register_strategy",
    "register_template",
    "replace_version_instruments",
    "resolve_params",
    "save_replay",
    "summarize_instances",
    "target_quantity",
    "update_instance",
    "update_strategy",
]
