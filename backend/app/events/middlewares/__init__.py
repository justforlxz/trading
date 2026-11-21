"""中间件：管线的每一道工序，按 `pipeline.DEFAULT_MIDDLEWARES` 的顺序执行。

每个模块只发布一个 `middleware` 工厂：`(PipelineDeps) -> Middleware`。
"""

__all__: list[str] = []
