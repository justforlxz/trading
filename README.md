# trading

自托管的自动化量化交易系统：分析美股之间的动态相关性、市场共振、趋势与相对强弱，构建多空组合策略，在 OKX 美股 USDT 本位永续合约上执行。

> 本仓库当前只有设计文档，**没有业务实现代码**。实现从 S2 开始，按 `docs/plan/p1.md` 的任务顺序推进。

## 当前阶段

**P1 交易前准备 · S1 开工检查与总体架构设计（已完成）**

| 项 | 状态 |
| --- | --- |
| 仓库基线 | 空仓（远程 refs = 0，2026-11-06 核查），首个提交即本文档集 |
| 技术栈 | Python 3.12 + FastAPI 后端；React 18 + Vite + TS 前端；PostgreSQL 16 + Redis 7；Docker Compose |
| 阶段范围 | 行情采集、股票关系分析、全市场机会发现、策略生成与审批、历史回测与评估 |
| 明确不做 | 模拟交易、真实下单、风控执行、AI 参与交易决策（P2/P3/P4） |
| 待决策 | 3 项，见 `docs/risk/external-dependencies.md` §5 |

## 文档索引

| 文档 | 内容 |
| --- | --- |
| `docs/architecture/overview.md` | 模块边界、依赖方向、运行容器与启动顺序、故障域 |
| `docs/architecture/data-model.md` | 实体、关键字段、唯一约束与幂等键、时间与精度约定 |
| `docs/architecture/api-contract.md` | 对外 REST 契约草案、错误与分页约定、实体↔资源映射 |
| `docs/plan/p1.md` | P1 任务拆解（依赖 / 交付物 / 验收命令 / 判据）与 S3–S8 映射 |
| `docs/risk/external-dependencies.md` | OKX 与美股行情源实测证据、结论、风险与待决策项 |
| `docs/architecture/adr/` | 架构决策记录 0001–0006 |

## 探针脚本

调研结论都可复现，脚本只读、无副作用、仅用 Python 标准库：

```bash
python3 scripts/probes/okx_probe.py all        # 合约清单 / 行情 / 资金费率 / 历史深度
python3 scripts/probes/equity_probe.py all     # 真实美股行情源可得性
python3 scripts/probes/okx_probe.py --help
python3 scripts/probes/equity_probe.py --help
```

## 本地开发（S2 落地后可用）

```bash
make up      # docker compose up -d，等待健康检查
make logs
make test
make down
```

在 S2 完成前上述命令尚不存在，这是预期状态，不是缺陷。
