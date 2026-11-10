"""健康检查：只回答「本进程是否活着」，不探测上游依赖。"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app import __version__
from app.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """稳定的探针响应结构，前端与运维脚本按字段读取。"""

    status: Literal["ok"]
    version: str
    env: str

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"status": "ok", "version": "0.2.0", "env": "dev"}]}
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """存活探针：进程能应答即返回 ok。"""

    return HealthResponse(status="ok", version=__version__, env=get_settings().app_env)
