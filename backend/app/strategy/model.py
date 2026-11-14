"""策略的持久化模型：v6 用户策略四张表，以及保留给自动化阶段的模板与实例表。

v6 新增的四张表是 `strategies`、`strategy_versions`、`strategy_instruments` 与
`strategy_linked_backtests`：策略是身份，版本是不可变的规则与参数快照，标的挂在
版本上，回测通过关联表指向版本。本段的其余说明仍描述模板与实例那两张旧表，它们
保留给执行与审批阶段，不再通过 HTTP 暴露。

模板的内容来自代码注册表（`app/strategy/registry.py` 的 import-time 登记），表里的行
是它的只读投影。投影的写入方不是本域：本域不碰会话，也没有写模板的入口；把登记表
写进这张表是装配层的职责（策略 API 节点 T3.3 在提供模板目录时顺带落库）。本节点只
定义结构，因此这里没有 `sync_templates()` 之类的方法——在出现第一个写入方之前，
写它等于凭空造一个没人调用的入口。

实例是用户配置（参数、标的、启停），可增删改，但只能引用已存在的模板：`strategy_id`
是指向模板表的外键，所以装配层必须先投影模板、再建实例，否则父表为空会直接报外键错。

两表分开而不是合并成一张：模板是代码事实，实例是用户数据，塞进同一张表迟早会出现
「改参数顺手改了模板」的写路径，而模板一旦能被用户改，「同版本可复现」就不成立了。

实例的字段与对外契约 `app/api/schemas/strategy.py::StrategyInstance` 基本一一对应
（含 `strategy_version`），避免接口层再翻译一次；`strategy_version` 记的是**实例创建
时**模板的版本，不是当前版本：模板升级后历史实例仍报自己那一版，回放才有依据。

例外有两处：生命周期阶段的列名是 `lifecycle_status`，契约里叫 `status`，同一个事实
只有一个列，且只能经审批状态机（`app/strategy/approval.py`）推进，通用的实例更新路径
不写它；`approved_by` 等四个推进凭据只在域内使用，契约没有对应字段，接口层也不映射。

时间列沿用 `candles` 的口径：存 epoch 秒（整数）；参数与标的是 JSON 文本，读回时
由使用方解析——两张表都不做业务校验，校验在模板的参数 schema 里做一次。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UtcDateTime

__all__ = [
    "StrategyApprovalRow",
    "StrategyInstanceRow",
    "StrategyInstrumentRow",
    "StrategyLinkedBacktestRow",
    "StrategyReplayRow",
    "StrategyTemplateRow",
    "StrategyVersionRow",
    "UserStrategyRow",
]


class StrategyTemplateRow(Base):
    """一个组合模板的只读投影：登记名即主键，内容与代码里的声明一致。

    `version` 与 `StrategyMeta.version` 同值。模板换了组合逻辑就换一行版本，历史实例
    指向的旧版本由此可查。
    """

    __tablename__ = "strategy_templates"

    strategy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class StrategyInstanceRow(Base):
    """一个用户配置的策略实例：引用模板 + 自己的参数与标的。

    `strategy_id` 是外键：实例不能指向一个不存在的模板，否则「这个实例用的是哪套
    组合方式」就没有答案。`strategy_version` 是实例创建时模板的版本（不是模板当前
    版本），模板升级不回头改它——否则历史实例会跟着报新版本，复现失去依据。
    `params` 与 `inst_ids` 是 JSON 文本（对象 / 数组），解析与校验在使用方进行。
    """

    __tablename__ = "strategy_instances"

    instance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("strategy_templates.strategy_id"), nullable=False, index=True
    )
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    bar: Mapped[str] = mapped_column(String(8), nullable=False)
    params: Mapped[str] = mapped_column(String(1024), nullable=False, default="{}")
    inst_ids: Mapped[str] = mapped_column(String(1024), nullable=False, default="[]")
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    latest_signal_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    # 生命周期的推进凭据：审核通过的人与时刻、达标报告编号、实盘授权时刻。四列都由
    # 审批状态机按目标阶段写入（见 `app/strategy/approval.py`），实例表自己不推断。
    # 未发生的推进留空——空值表达「还没发生」，不写空串或 0 冒充一个时刻。
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_report_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    live_authorized_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class StrategyReplayRow(Base):
    """一次目标组合回放的结果：区间 + 规范化目标组合 + 逐点敞口序列。

    回放是「按历史行情把模板重算一遍」的执行记录，不是策略配置：同一实例、同一区间
    回放两次会得到两行，但两行的 `target_hash` 必须相同（这是可复现的判据）。因此
    不按内容做幂等去重——重复行记录的是「又算了一次」，而算出来的东西是否一致由
    `target_hash` 回答。

    `result_json` 存目标组合的每条腿（含 `product_key`，按它排序）与净敞口；
    `points_json` 存逐点净敞口序列，供页面画单条折线。两者都是 JSON 文本，读回时由
    使用方解析，与实例表的 params / inst_ids 同口径。
    """

    __tablename__ = "strategy_replays"

    replay_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("strategy_instances.instance_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bar: Mapped[str] = mapped_column(String(8), nullable=False)
    start_at: Mapped[int] = mapped_column(Integer, nullable=False)
    end_at: Mapped[int] = mapped_column(Integer, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    points_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class StrategyApprovalRow(Base):
    """一次生命周期推进的记录：谁、在什么时刻、把哪个实例从哪个阶段推到哪个阶段。

    记录是历史事实，只增不改：阶段推进被驳回或回退时，旧记录仍然说明「当初是谁批的、
    依据是什么」，回退本身是另一条记录。`instance_id` 带 `ON DELETE CASCADE`：实例
    删掉之后，它的审批记录没有独立意义。

    `evidence` 存推进依据的引用：进入 `validated` 时是达标报告的编号，其余阶段是调用方
    给的引用（例如审批单号），没有依据时留空。`from_status` 允许为空是为了容纳
    「机会发现直接产出实例」这种没有前一阶段的情况；本模块的推进总会带上它。

    `seq` 是写入顺序，由数据库序列发放，不复用也不回收。`at` 只有秒精度，同一秒内的
    多条推进光看时间无法分出先后，而审批记录列表必须按「先发生先列」的顺序展示，
    排序因此落在 `seq` 上。
    """

    __tablename__ = "strategy_approvals"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    instance_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("strategy_instances.instance_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    at: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    evidence: Mapped[str | None] = mapped_column(String(256), nullable=True)


class UserStrategyRow(Base):
    """v6 用户策略：名称、类别与状态；具体规则在版本行里。

    策略本身不是可执行配置：它只有身份与展示属性。规则、参数、周期、方向和标的都
    落在版本上，改规则必须新建版本，历史回测引用的那一版因此不会被后续修改覆盖。
    状态取 `draft` / `validated` / `enabled` / `paused` / `archived`，只控制页面展示与
    后续自动化阶段的启用范围，本版本不据此下单。
    """

    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class StrategyVersionRow(Base):
    """策略的一个不可变版本：规则、参数、周期、方向、仓位规则与成本假设。

    `version` 从 1 开始按策略递增，`(strategy_id, version)` 唯一。版本行创建后不再
    修改；需要换规则时新建下一版。历史回测通过 `strategy_linked_backtests` 指向
    具体版本，因此回测结论始终能追到当时那一套规则。
    """

    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "version", name="uq_strategy_versions"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_json: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    position_sizing_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_model_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class StrategyInstrumentRow(Base):
    """策略版本关联的标的集合；主键保证同一版本不会重复登记同一标的。"""

    __tablename__ = "strategy_instruments"

    strategy_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("strategy_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    instrument_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("instruments.symbol", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class StrategyLinkedBacktestRow(Base):
    """策略版本与回测运行的多对多关联：回测记录由此反查策略，不用名称模糊匹配。"""

    __tablename__ = "strategy_linked_backtests"

    strategy_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("strategy_versions.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    backtest_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
