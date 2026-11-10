"""HTTP 协议层：只做入参校验与响应组装，业务规则不进这一层。

门面只发布可挂载的路由对象；端点与响应模型属于本包内部实现。
`contract_router` 是七个业务域的契约桩，真实端点落地时替换同名路径。
"""

from app.api.contract import contract_router
from app.api.health import router as health_router

__all__ = ["contract_router", "health_router"]
