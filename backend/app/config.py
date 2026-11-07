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

    # 公共行情接口（P1 只用公开 REST，不接私有/下单接口）。
    okx_rest_base_url: str = "https://www.okx.com"
    okx_http_timeout_seconds: float = 10.0
    # 实测限流阈值：/market/candles 40 次/2s，/market/history-candles 20 次/2s。
    okx_candles_rate_limit: int = 40
    okx_history_rate_limit: int = 20
    okx_rate_limit_window_seconds: float = 2.0
    okx_max_retries: int = 4
    okx_retry_backoff_seconds: float = 0.5

    # 真实美股行情源：yahoo（免 key，无 SLA）或 none（显式缺失）。
    equity_source: str = "yahoo"
    equity_http_timeout_seconds: float = 10.0
    equity_daily_lookback_days: int = 10
    # 周期同步的真实行情标的（股票代码，逗号分隔）。P1 先控制在少量标的，
    # 避免每 5 分钟对 175 个标的打满 Yahoo 的无 SLA 接口。
    equity_sync_symbols: str = "AAPL,SPY,QQQ,NVDA,TSLA"

    # 采集周期任务：秒为单位的调度间隔。
    sync_instruments_interval_seconds: int = 3600
    ingest_candles_interval_seconds: int = 60
    sync_equity_interval_seconds: int = 300
    quality_interval_seconds: int = 900
    retention_interval_seconds: int = 86400
    sync_sessions_interval_seconds: int = 86400

    # 周期采集的 bar 与标的范围（P1 不扫全市场，靠 /market/backfill 补齐单标的）。
    ingest_bars: str = "1m,5m,15m,1h,4h,1d"
    candle_ingest_symbols: str = "AAPL,SPY,QQQ,NVDA,TSLA"

    # 保留策略与质量阈值。
    rolling_retention_days: int = 90
    basis_alert_bps: int = 500
    stale_after_seconds: int = 600

    # 研究域默认参数（请求体未显式给定时由 API/任务填充）。
    # 相关性窗口按 K 线根数切，不随时段开关变化。
    research_bar: str = "1d"
    relation_window_bars: int = 60
    relation_lag_max: int = 5
    relation_stability_window: int = 20
    # 系数变化超过该阈值或符号翻转即视为显著变化。
    relation_change_threshold: float = 0.2
    relative_strength_lookback: int = 60

    # S5 全市场机会发现：特征窗口、聚类与机会判定阈值都从配置注入，不写死在函数里。
    opportunity_bar: str = "1d"
    opportunity_lookback_bars: int = 60
    opportunity_min_overlap: int = 20
    opportunity_cluster_threshold: float = 0.6
    opportunity_min_cluster_size: int = 3
    opportunity_min_correlation: float = 0.6
    opportunity_spread_z: float = 1.5
    opportunity_resonance_threshold: float = 0.6
    opportunity_anomaly_window: int = 20
    opportunity_anomaly_min_corr: float = 0.7
    opportunity_anomaly_min_delta: float = 0.4
    opportunity_max_pairs: int = 40
    opportunity_scan_interval_seconds: int = 3600

    # S6 策略构建与审批：权重空间与腿数上限都从配置注入，构建器只做纯计算。
    # 单标的权重上限 0.6 保证两腿各 0.5 的组合合法，且不会退化成单腿押注。
    strategy_max_position_weight: float = 0.6
    strategy_max_gross_exposure: float = 1.0
    strategy_max_net_exposure: float = 1.0
    strategy_min_legs: int = 2
    strategy_max_legs: int = 6

    # S7 历史回测：窗口上限从配置注入，公式里不写死；年化因子按 bar 推导。
    backtest_max_bars: int = 20000


@lru_cache
def get_settings() -> Settings:
    """按进程缓存配置，避免每次请求重复解析环境变量。"""

    return Settings()
