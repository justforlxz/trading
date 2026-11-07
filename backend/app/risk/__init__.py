"""P2 风控：策略级与全局组合两级风控。

分层约定：

- ``app.risk.core`` 只放纯函数（输入 dataclass + ``Decimal``，输出判决或抛
  :class:`RiskError`），不访问数据库、不发网络请求、不读配置。
- ``app.risk.service`` 只做查询、编排与落库，计算一律委托给 ``core``。
- ``app.risk.data`` 用独立 ``MetaData`` 只读声明 ``strategy`` / ``market`` /
  ``backtest`` 表，避免 ``strategy``/``backtest`` 反向依赖风控。

本模块不接触真实账户，不引用执行域 ``execution`` 与 ``ai``，不做任何下单类调用。
"""
