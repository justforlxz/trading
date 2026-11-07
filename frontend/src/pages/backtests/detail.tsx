import { Loader2, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { PageHeading } from "../../components/layout/page-parts";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import * as api from "../../lib/api";
import type {
  BacktestCriteria,
  BacktestEquityPoint,
  BacktestMetric,
  BacktestRun,
  BacktestTrade,
} from "../../lib/api";
import { cn } from "../../lib/utils";
import { Chart } from "../research/chart";

const METRIC_LABELS: Record<string, string> = {
  total_return: "总收益",
  annualized_return: "年化收益",
  max_drawdown: "最大回撤",
  sharpe: "夏普比率",
  sortino: "索提诺比率",
  win_rate: "胜率",
  profit_loss_ratio: "盈亏比",
  trade_count: "成交笔数",
  turnover: "换手率",
  cost_ratio: "成本占比",
};

function describe(error: unknown): string {
  if (error instanceof api.ApiError) {
    return `${error.code}：${error.message}`;
  }
  return error instanceof Error ? error.message : "未知错误";
}

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function describeMetricName(name: string): { label: string; window: string | null } {
  const [base, window] = name.split("@", 2);
  return { label: METRIC_LABELS[base] ?? base, window: window ?? null };
}

const STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "计算中",
  ok: "已完成",
  failed: "失败",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs",
        status === "ok"
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
          : status === "failed"
            ? "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400"
            : "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
      )}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function CriteriaPanel({ criteria }: { criteria: BacktestCriteria | null }) {
  if (!criteria) return null;
  return (
    <div
      className={cn(
        "rounded-lg border px-4 py-3 text-sm",
        criteria.results.length > 0 && criteria.passed
          ? "border-emerald-500/40 bg-emerald-500/5"
          : criteria.results.length > 0
            ? "border-red-500/40 bg-red-500/5"
            : "border-border/60",
      )}
    >
      <p className="mb-2 font-medium">
        验证标准
        {criteria.default ? "（默认标准）" : ""}
        {criteria.results.length > 0 ? (
          <span className={criteria.passed ? "ml-2 text-emerald-600" : "ml-2 text-red-600"}>
            {criteria.passed ? "通过" : "未通过"}
          </span>
        ) : (
          <span className="ml-2 text-muted-foreground">等待计算</span>
        )}
      </p>
      {criteria.results.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          指标计算完成后写入判定结果；通过与否只由阈值决定，不随策略状态变化。
        </p>
      ) : (
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-b text-left uppercase tracking-[0.08em] text-muted-foreground">
              <th className="py-1.5 pr-4 font-medium">指标</th>
              <th className="py-1.5 pr-4 font-medium">条件</th>
              <th className="py-1.5 pr-4 font-medium">实际</th>
              <th className="py-1.5 font-medium">结果</th>
            </tr>
          </thead>
          <tbody>
            {criteria.results.map((item) => (
              <tr key={`${item.name}-${item.op}`} className="border-b border-border/60 last:border-0">
                <td className="py-1.5 pr-4">{METRIC_LABELS[item.name] ?? item.name}</td>
                <td className="py-1.5 pr-4 font-mono">
                  {item.op} {item.threshold}
                </td>
                <td className="py-1.5 pr-4 font-mono">{item.actual}</td>
                <td className={cn("py-1.5", item.passed ? "text-emerald-600" : "text-red-600")}>
                  {item.passed ? "通过" : "未通过"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

async function loadAllEquity(runId: number): Promise<BacktestEquityPoint[]> {
  const items: BacktestEquityPoint[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < 100; page += 1) {
    const result = await api.listBacktestEquity(runId, { limit: 2000, cursor });
    items.push(...result.items);
    if (!result.next_cursor) break;
    cursor = result.next_cursor;
  }
  return items;
}

async function loadAllTrades(runId: number): Promise<BacktestTrade[]> {
  const items: BacktestTrade[] = [];
  let cursor: number | undefined;
  for (let page = 0; page < 100; page += 1) {
    const result = await api.listBacktestTrades(runId, { limit: 200, cursor });
    items.push(...result.items);
    if (result.next_cursor === null) break;
    cursor = result.next_cursor;
  }
  return items;
}

export default function BacktestDetailPage() {
  const params = useParams();
  const runId = Number(params.id);

  const [run, setRun] = useState<BacktestRun | null>(null);
  const [metrics, setMetrics] = useState<BacktestMetric[]>([]);
  const [equity, setEquity] = useState<BacktestEquityPoint[]>([]);
  const [trades, setTrades] = useState<BacktestTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function poll() {
      try {
        const latest = await api.getBacktest(runId);
        if (cancelled) return;
        setRun(latest);
        setError(null);
        if (latest.status === "queued" || latest.status === "running") {
          timer = window.setTimeout(poll, 1500);
        }
      } catch (caught) {
        if (!cancelled) setError(describe(caught));
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runId, reloadToken]);

  useEffect(() => {
    if (!run || run.status !== "ok") return;
    let cancelled = false;
    async function load() {
      try {
        const [metricResult, curve, tradeRows] = await Promise.all([
          api.getBacktestMetrics(runId),
          loadAllEquity(runId),
          loadAllTrades(runId),
        ]);
        if (cancelled) return;
        setMetrics(metricResult.items);
        setEquity(curve);
        setTrades(tradeRows);
        setError(null);
      } catch (caught) {
        if (!cancelled) setError(describe(caught));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [run, runId]);

  const chartOption = useMemo(() => {
    const timestamps = equity.map((point) => point.ts);
    return {
      animation: false,
      grid: { left: 64, right: 52, top: 28, bottom: 40 },
      tooltip: { trigger: "axis" as const },
      xAxis: {
        type: "category" as const,
        data: timestamps,
        axisLabel: { formatter: (value: string) => value.slice(0, 10) },
      },
      yAxis: [
        { type: "value" as const, scale: true, name: "权益" },
        {
          type: "value" as const,
          scale: true,
          name: "回撤 %",
          axisLabel: { formatter: (value: number) => `${value}` },
        },
      ],
      series: [
        {
          name: "权益",
          type: "line" as const,
          showSymbol: false,
          data: equity.map((point) => Number(point.equity)),
          lineStyle: { width: 1.5 },
        },
        {
          name: "回撤 %",
          type: "line" as const,
          yAxisIndex: 1,
          showSymbol: false,
          data: equity.map((point) => Number(point.drawdown) * 100),
          lineStyle: { width: 1 },
          areaStyle: { opacity: 0.12 },
        },
      ],
    };
  }, [equity]);

  if (Number.isNaN(runId)) {
    return <p className="text-sm text-muted-foreground">无效的回测编号。</p>;
  }

  return (
    <>
      <PageHeading
        eyebrow="Backtests"
        title={`回测报告 #${runId}`}
        description="历史回测只读行情与策略：建仓于窗口内首根已确认 K 线，持有到窗口结束平仓；报告中的数值全部来自后端计算，页面只做格式化呈现。"
      />

      {error && (
        <p className="mb-4 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400">
          {error}
        </p>
      )}

      {!run && !error && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          正在读取回测运行…
        </p>
      )}

      {run && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-3">
                <CardTitle>运行信息</CardTitle>
                <StatusBadge status={run.status} />
                <span className="text-xs text-muted-foreground">
                  {run.status === "queued" || run.status === "running"
                    ? "后台任务执行中，页面会自动刷新"
                    : null}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto"
                  onClick={() => setReloadToken((token) => token + 1)}
                >
                  <RefreshCw className="size-3.5" />
                  刷新
                </Button>
              </div>
              <CardDescription>
                策略 #{run.strategy_id} · 版本 v{run.strategy_version} · 周期 {run.bar} ·
                窗口 {formatTimestamp(run.window.start)} → {formatTimestamp(run.window.end)}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                <div className="flex gap-2">
                  <dt className="w-24 shrink-0 text-muted-foreground">初始资金</dt>
                  <dd className="font-mono">{run.initial_capital}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-24 shrink-0 text-muted-foreground">运行指纹</dt>
                  <dd className="truncate font-mono text-xs" title={run.run_key}>
                    {run.run_key}
                  </dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-24 shrink-0 text-muted-foreground">开始时间</dt>
                  <dd>{formatTimestamp(run.started_at)}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-24 shrink-0 text-muted-foreground">结束时间</dt>
                  <dd>{formatTimestamp(run.finished_at)}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-24 shrink-0 text-muted-foreground">价格基准</dt>
                  <dd className="font-mono">{String(run.params.price_basis ?? "—")}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-24 shrink-0 text-muted-foreground">数据来源</dt>
                  <dd className="font-mono">{String(run.params.data_source ?? "—")}</dd>
                </div>
              </dl>

              {run.funding_assumption === "constant" && (
                <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
                  资金费口径：常数假设（每个 8 小时结算周期按固定 bps 计），
                  系统当前没有真实资金费采集，报告不声称使用实测资金费。
                </p>
              )}

              <div className="rounded-lg border border-border/60 p-3 text-sm">
                <p className="mb-2 font-medium">成本假设</p>
                <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
                  <div className="flex gap-2">
                    <dt className="text-muted-foreground">Taker</dt>
                    <dd className="font-mono">{run.cost_model.taker_fee_bps} bps</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-muted-foreground">Maker</dt>
                    <dd className="font-mono">{run.cost_model.maker_fee_bps} bps</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-muted-foreground">滑点</dt>
                    <dd className="font-mono">{run.cost_model.slippage_bps} bps</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-muted-foreground">资金费</dt>
                    <dd className="font-mono">
                      {run.cost_model.funding_bps_per_period} bps / 8h
                    </dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-muted-foreground">费率角色</dt>
                    <dd className="font-mono">{run.cost_model.fee_role}</dd>
                  </div>
                </dl>
              </div>

              {run.error && (
                <p className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 font-mono text-xs text-red-700 dark:text-red-400">
                  {run.error}
                </p>
              )}

              <CriteriaPanel criteria={run.criteria} />
            </CardContent>
          </Card>

          {run.status === "ok" && (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>指标</CardTitle>
                  <CardDescription>
                    多窗口回测时，带 <code>@窗口名</code> 的行是分段结果，未带后缀的是整段汇总。
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="-mx-1 overflow-x-auto px-1">
                    <table className="w-full min-w-[520px] border-collapse text-sm">
                      <thead>
                        <tr className="border-b text-left text-xs uppercase tracking-[0.08em] text-muted-foreground">
                          <th className="py-2 pr-4 font-medium">指标</th>
                          <th className="py-2 pr-4 font-medium">窗口</th>
                          <th className="py-2 pr-4 font-medium">值</th>
                          <th className="py-2 font-medium">单位</th>
                        </tr>
                      </thead>
                      <tbody>
                        {metrics.map((metric) => {
                          const { label, window } = describeMetricName(metric.name);
                          return (
                            <tr key={metric.name} className="border-b border-border/60 last:border-0">
                              <td className="py-2 pr-4">{label}</td>
                              <td className="py-2 pr-4 font-mono text-xs text-muted-foreground">
                                {window ?? "整段"}
                              </td>
                              <td className="py-2 pr-4 font-mono">{metric.value}</td>
                              <td className="py-2 text-xs text-muted-foreground">{metric.unit}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>权益与回撤</CardTitle>
                  <CardDescription>
                    权益曲线按每个已确认 bar 的收盘价估值；回撤为相对历史峰值的比例（≤ 0）。
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {equity.length === 0 ? (
                    <p className="text-sm text-muted-foreground">没有权益点。</p>
                  ) : (
                    <Chart option={chartOption} height={320} />
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>成交明细</CardTitle>
                  <CardDescription>
                    回测虚拟持仓流水，不是真实成交；`fees`、`funding`、`slippage` 为成本拆解，
                    `net_pnl = gross_pnl - fees - funding`（滑点已计入成交价）。
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {trades.length === 0 ? (
                    <p className="text-sm text-muted-foreground">没有成交。</p>
                  ) : (
                    <div className="-mx-1 overflow-x-auto px-1">
                      <table className="w-full min-w-[980px] border-collapse text-sm">
                        <thead>
                          <tr className="border-b text-left text-xs uppercase tracking-[0.08em] text-muted-foreground">
                            <th className="py-2 pr-4 font-medium">标的</th>
                            <th className="py-2 pr-4 font-medium">方向</th>
                            <th className="py-2 pr-4 font-medium">建仓</th>
                            <th className="py-2 pr-4 font-medium">平仓</th>
                            <th className="py-2 pr-4 font-medium">成交价</th>
                            <th className="py-2 pr-4 font-medium">净盈亏</th>
                            <th className="py-2 pr-4 font-medium">成本拆解</th>
                            <th className="py-2 font-medium">持仓 bar</th>
                          </tr>
                        </thead>
                        <tbody>
                          {trades.map((trade) => (
                            <tr key={trade.id} className="border-b border-border/60 last:border-0">
                              <td className="py-2 pr-4">
                                <span className="font-medium">
                                  {trade.symbol ?? trade.inst_id ?? trade.instrument_id}
                                </span>
                                <span className="block font-mono text-xs text-muted-foreground">
                                  {trade.inst_id ?? `#${trade.instrument_id}`}
                                </span>
                              </td>
                              <td
                                className={cn(
                                  "py-2 pr-4",
                                  trade.side === "long"
                                    ? "text-emerald-700 dark:text-emerald-400"
                                    : "text-red-700 dark:text-red-400",
                                )}
                              >
                                {trade.side === "long" ? "多" : "空"}
                              </td>
                              <td className="py-2 pr-4 text-xs">{formatTimestamp(trade.entry_ts)}</td>
                              <td className="py-2 pr-4 text-xs">{formatTimestamp(trade.exit_ts)}</td>
                              <td className="py-2 pr-4 font-mono text-xs">
                                {trade.entry_px} → {trade.exit_px}
                                <span className="block text-muted-foreground">qty {trade.qty}</span>
                              </td>
                              <td
                                className={cn(
                                  "py-2 pr-4 font-mono",
                                  Number(trade.net_pnl) >= 0
                                    ? "text-emerald-700 dark:text-emerald-400"
                                    : "text-red-700 dark:text-red-400",
                                )}
                              >
                                {trade.net_pnl}
                                <span className="block text-xs text-muted-foreground">
                                  gross {trade.gross_pnl}
                                </span>
                              </td>
                              <td className="py-2 pr-4 font-mono text-xs">
                                <span className="block">fee {trade.fees}</span>
                                <span className="block">funding {trade.funding}</span>
                                <span className="block">slip {trade.slippage}</span>
                              </td>
                              <td className="py-2 text-xs text-muted-foreground">
                                {trade.bars_held}
                                <span className="block font-mono">{trade.exit_reason}</span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CardContent>
              </Card>
            </>
          )}

          <p className="text-xs text-muted-foreground">
            返回 <Link className="underline" to="/strategies">策略列表</Link>
          </p>
        </div>
      )}
    </>
  );
}
