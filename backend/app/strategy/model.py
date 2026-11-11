"""策略模板与策略实例两张表：模板只读，实例是用户配置。

模板的内容来自代码注册表（`app/strategy/registry.py` 的 import-time 登记），表里的行
是它的只读投影。投影的写入方不是本域：本域不碰会话，也没有写模板的入口；把登记表
写进这张表是装配层的职责（策略 API 节点 T3.3 在提供模板目录时顺带落库）。本节点只
定义结构，因此这里没有 `sync_templates()` 之类的方法——在出现第一个写入方之前，
写它等于凭空造一个没人调用的入口。

实例是用户配置（参数、标的、启停），可增删改，但只能引用已存在的模板：`strategy_id`
是指向模板表的外键，所以装配层必须先投影模板、再建实例，否则父表为空会直接报外键错。

两表分开而不是合并成一张：模板是代码事实，实例是用户数据，塞进同一张表迟早会出现
「改参数顺手改了模板」的写路径，而模板一旦能被用户改，「同版本可复现」就不成立了。

实例的字段与对外契约 `app/api/schemas/strategy.py::StrategyInstance` 一一对应（含
`strategy_version`），避免接口层再翻译一次。`strategy_version` 记的是**实例创建时**
模板的版本，不是当前版本：模板升级后历史实例仍报自己那一版，回放才有依据。生命周期
阶段（`status`）不在本表推进，只经审批状态机改。

时间列沿用 `candles` 的口径：存 epoch 秒（整数）；参数与标的是 JSON 文本，读回时
由使用方解析——两张表都不做业务校验，校验在模板的参数 schema 里做一次。
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

__all__ = ["StrategyInstanceRow", "StrategyTemplateRow"]


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
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    latest_signal_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
