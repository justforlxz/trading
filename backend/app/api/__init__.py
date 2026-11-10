"""HTTP 协议层门面：只发布装配入口，端点与响应模型属于本包内部实现。

端点按业务域拆在 `app.api.routes` 下，由 `app.api.registry` 统一挂载；域层异常由
`app.api.errors` 翻译成 HTTP 响应，状态码只在边界读取一次。
"""

from app.api.errors import register_error_handlers
from app.api.registry import include_routers

__all__ = ["include_routers", "register_error_handlers"]
