"""进程配置：唯一来源是环境变量（`.env.example` 是清单，密钥不入库）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行期配置。

    字段名即环境变量名（大小写不敏感）：`DATABASE_URL`、`REDIS_URL` 等。
    默认值只用于本地与 Compose 开发，生产环境必须显式注入。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://trading:trading@postgres:5432/trading"
    redis_url: str = "redis://redis:6379/0"

    # scheduler 存活探针：每隔 interval 写一次心跳，超过 timeout 视为失联。
    scheduler_heartbeat_interval_seconds: float = 5.0
    scheduler_heartbeat_timeout_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    """按进程缓存配置，避免每次请求重复解析环境变量。"""

    return Settings()
