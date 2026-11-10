"""HTTP 协议层：只做入参校验与响应组装，业务规则不进这一层。

门面只发布可挂载的路由对象；端点与响应模型属于本包内部实现。
"""

from app.api.health import router as health_router

__all__ = ["health_router"]
