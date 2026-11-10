"""进程配置：唯一来源是环境变量（仓库根的 `.env.example` 是清单，密钥不入库）。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 后端包所在目录：库文件位置按包路径反推，不依赖进程 cwd。
BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """运行期配置。

    字段名即环境变量名（大小写不敏感）。默认值只用于本地开发，
    CI 与生产环境由外部显式注入。
    """

    model_config = SettingsConfigDict(
        # 仓库根的 `.env`（AGENTS.md 的 `cp .env.example .env` 落点），与进程 cwd 无关：
        # 后端常以 backend/ 为 cwd 启动，写相对路径会让根 `.env` 被静默忽略。
        env_file=BACKEND_DIR.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    log_level: str = "INFO"

    # SQLite 单文件库：固定落在 backend/data/ 下，由 init_db 建目录与表。
    database_path: Path = BACKEND_DIR / "data" / "trading.db"

    # 公共行情上游地址（只读公开 REST，不涉及下单）。
    okx_rest_base_url: str = "https://www.okx.com"
    okx_http_timeout_seconds: float = 10.0
    # 限流重试上限：命中上游限流后最多再试几次，用尽即报「限流」错误。
    okx_http_max_retries: int = 3
    # 令牌桶容量与补充速率：按上游最紧的公共行情配额（20 次 / 2 秒）折算。
    okx_rate_limit_capacity: int = 20
    okx_rate_limit_refill_per_second: float = 10.0


@lru_cache
def get_settings() -> Settings:
    """按进程缓存配置，避免每次请求重复解析环境变量。"""

    return Settings()
