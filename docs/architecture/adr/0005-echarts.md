# ADR-0005：统一使用 ECharts 承载所有图表

- 状态：已接受
- 日期：2026-11-06
- 相关：`docs/architecture/overview.md` §3、`docs/plan/p1.md` P1-10 / P1-13 / P1-20

## 上下文

前端需要四类图：驾驶舱的轻量走势与分布、研究页的**关系网络图**（节点=标的，边=相关系数）、回测页的**K 线与权益/回撤曲线**、以及策略腿的权重展示。项目要求"Apple 风格 + 专业金融终端"，浅色/深色双主题，桌面优先（1440px+）。引入图表库越少，主题与交互一致性越好。

## 决策

统一使用 **Apache ECharts**（按需 `echarts/core` + 逐图表注册），不引入第二个图表库。

- K 线：`candlestick` + `dataZoom` + `markLine`（策略入场/出场标记）。
- 曲线：`line` / `areaStyle`（权益、回撤、相关性时间序列）。
- 关系网络：`graph`（force 布局），节点大小映射连接强度，边宽映射 |coefficient|。
- 轻量图：`bar` / `scatter` / `heatmap`。
- 主题：一套自定义 theme 提供 light/dark 两个变体，颜色 token 与 Tailwind 设计系统同源。

## 后果

正面：

- 一个库覆盖全部图表，主题、tooltip、缩放、导出行为一致，用户不需要在不同页面适应不同交互。
- `graph` 支持力导向布局与拖拽（仅用于查看，不回写数据），满足"关系网络只用于分析展示"的约束。
- 按需注册后包体可控（candlestick + line + graph 约数百 KB，可接受）。

负面 / 代价：

- 包体大于 `lightweight-charts`（后者专为 K 线，~45KB）。
- 大图性能：节点 >500 时力导向布局会卡；需要降级为"按度数裁剪 top-N + 聚类聚合"。
- 命令式 API，与 React 需要一层封装（`useECharts` hook 管理实例生命周期与 resize）。

## 为什么不是其它方案

| 备选 | 拒绝理由 |
| --- | --- |
| `lightweight-charts`（K 线）+ `Recharts`（曲线）+ `vis-network`（关系图） | 三套 API、三套主题、三种交互模型；三处都要实现深浅色适配；维护成本远大于省下的包体 |
| 只用 `Recharts` | 没有原生 candlestick，K 线需拼装 `Bar`，缩放与十字光标体验差；无关系图能力 |
| `D3` 全自绘 | 自由度最高但开发与维护成本最高，P1 没有定制到需要自绘的程度 |
| `vis-network` 单做关系图 | 项目活跃度低，主题与交互无法与其它图表统一 |

## 复核触发条件

关系网络稳定超过 1000 个可见节点，或需要 GPU 级渲染/大规模图布局；届时评估把关系图单独换成 WebGL 方案（如 `sigma.js`），其余图表仍用 ECharts。
