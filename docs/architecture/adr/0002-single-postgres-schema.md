# ADR-0002：单 PostgreSQL 实例 + Schema 分域，而非分库

- 状态：已接受
- 日期：2026-11-06
- 相关：`docs/architecture/data-model.md`

## 上下文

领域有五个上下文：`market`（行情）、`research`（关系）、`opportunity`（机会，实际落在 research 之外独立 schema）、`strategy`、`backtest`、`ops`。它们之间存在真实的外键与事务需求：回测必须绑定策略的某个版本；关系快照引用目标与合约；机会批次引用特征截面。数据量约 3900 万行（含 1m K 线 90 天保留）。

## 决策

单 PostgreSQL 16 实例，按 schema 分域：`market`、`research`、`strategy`、`backtest`、`opportunity`、`ops`。

- 跨 schema 允许的外键只有：引用 `market.instrument`、`research.target_symbol`、`strategy.strategy`。
- 禁止跨 schema JOIN 其它业务表；跨域读取必须经服务层函数或视图。
- 迁移按 schema 分文件，单实例单 `alembic upgrade head`。
- K 线表按 `open_time` 月分区，保留策略在分区层执行。

## 后果

正面：

- 策略版本 → 回测结果、关系快照 → 边，都是本地外键，一致性问题在数据库层解决。
- 备份/恢复只有一条路径；自托管运维简单。
- 分析查询（行情 + 关系 + 特征）可以单条 SQL 完成，避免把 227 标的的数据搬到应用层拼装。

负面 / 代价：

- 单实例是爆炸半径：数据库故障则全站不可用（已在 overview §7 列为故障域，选择直接暴露失败而不是过度设计降级）。
- 大表与业务表同库，VACUUM/autovacuum 与 IO 会互相影响；依赖分区与保留策略控制。
- schema 边界靠迁移评审与 CI 检查维持，数据库本身不强制"禁止跨 schema JOIN"。

## 为什么不是其它方案

| 备选 | 拒绝理由 |
| --- | --- |
| 每个上下文一个数据库 | 跨库外键不可用，回测与策略的强一致绑定要靠应用层补偿；个人自托管要维护 5 套连接、备份与迁移 |
| 行情单独用时序库（Timescale/ClickHouse） | 增加第二套存储与查询语言；3900 万行对 PG 分区完全可承受，过早引入使运维复杂度翻倍 |
| 单库单 schema（无分域） | 表名冲突与依赖无序，边界无从检查；schema 是最便宜的边界表达 |

## 复核触发条件

`market.candle` 单表超过 1 亿行且查询延迟不可接受；或写入并发成为瓶颈（需要独立实例/时序库）。届时只迁移 `market` 域，其余保持单实例。
