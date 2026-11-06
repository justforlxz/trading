"""arq 任务定义与调度入口（worker / scheduler 共用镜像、独立进程）。

P1 的任务（标的全量同步、K 线回补、全市场扫描、回测）从 S3 起陆续加入；
S2 只固定三件事：进程边界、`job_key` 幂等约定、失败重试语义。
"""

from app.jobs.keys import canonical_job_key, canonical_payload

__all__ = ["canonical_job_key", "canonical_payload"]
