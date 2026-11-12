import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { BacktestDetailResponse } from "../../lib/api";
import { instTypeLabel } from "../../lib/display";
import { formatParams } from "./format";
import { ReadingGrid, type Reading } from "./reading";

export type BacktestSummaryProps = {
  detail: BacktestDetailResponse;
};

/**
 * 组合级汇总卡片：资金与绩效一行，组合级四项（净敞口、多腿/空腿合计盈亏、资金费）一行。
 *
 * 逐腿明细在下面的表里；这张卡片只回答「整个组合怎么样」，所有数值都来自后端。
 */
export function BacktestSummary({ detail }: BacktestSummaryProps) {
  const { run, request, portfolio } = detail;
  const metrics = run.metrics;

  const performance: Reading[] = [
    { label: "初始资金", value: metrics?.initial_capital ?? "—" },
    { label: "最终资金", value: metrics?.final_capital ?? "—" },
    {
      label: "总收益率",
      value: metrics ? `${metrics.total_return_pct}%` : "—",
      tone: true,
    },
    { label: "最大回撤", value: metrics ? `${metrics.max_drawdown_pct}%` : "—" },
    { label: "Sharpe", value: metrics?.sharpe ?? "—" },
    { label: "交易次数", value: metrics ? String(metrics.trade_count) : "—" },
  ];

  const combined: Reading[] = [
    { label: "净敞口", value: portfolio.net_exposure, tone: true },
    { label: "多腿合计盈亏", value: portfolio.long_pnl, tone: true },
    { label: "空腿合计盈亏", value: portfolio.short_pnl, tone: true },
    { label: "资金费合计", value: metrics?.funding_total ?? "—" },
  ];

  const winRates = Object.entries(portfolio.leg_win_rate);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <CardTitle>
            组合级汇总 · {run.inst_id}
            <span className="ml-2 rounded-full border px-2 py-0.5 text-xs font-normal text-muted-foreground">
              {instTypeLabel(run.inst_type)}
            </span>
          </CardTitle>
          <span className="font-mono text-xs text-muted-foreground" title={run.run_id}>
            {run.run_id}
          </span>
        </div>
        <CardDescription>
          {request.start_date} ~ {request.end_date} · {request.bar} · {request.data_source} ·
          执行模型 {request.execution_model}
        </CardDescription>
        <p className="break-words font-mono text-xs text-muted-foreground">
          参数：{formatParams(run.params)}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <ReadingGrid readings={performance} />
        <ReadingGrid readings={combined} className="border-t pt-4 sm:grid-cols-2 lg:grid-cols-4" />
        <div className="text-xs text-muted-foreground">
          <span className="mr-2">每腿胜率</span>
          {winRates.length === 0 ? (
            <span>没有成交腿</span>
          ) : (
            winRates.map(([key, value]) => (
              <span key={key} className="mr-3 font-mono tabular-nums">
                {key}：{value}
              </span>
            ))
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          资金费覆盖率与缺口数未随本版结果落库；资金费结算接入回测主循环由后续节点承接，
          当前资金费合计恒为 0，不代表「没有资金费」。
        </p>
      </CardContent>
    </Card>
  );
}
