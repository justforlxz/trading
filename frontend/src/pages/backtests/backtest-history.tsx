import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { BacktestRunSummary } from "../../lib/api";
import { instTypeLabel, signedTone, signedValue } from "../../lib/display";
import { cn } from "../../lib/utils";
import { formatParams } from "./format";

export type BacktestHistoryPanelProps = {
  runs: BacktestRunSummary[];
  total: number;
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
  onDelete: (runId: string) => void;
  /** 策略页把版本标识映射成 `v1` 这类短标签；回测页不传，行为不变。 */
  versionLabels?: Record<string, string>;
};

function metricRow(label: string, value: string, tone = false) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("font-mono text-sm tabular-nums", tone && signedTone(value))}>{value}</dd>
    </div>
  );
}

/**
 * 历史结果：一次回测一张卡片，并排铺开，方便对比不同参数组合。
 *
 * 卡片只放后端返回的数值，不做任何派生计算，也不判断哪一张「更好」。
 */
export function BacktestHistoryPanel({
  runs,
  total,
  selectedRunId,
  onSelect,
  onDelete,
  versionLabels,
}: BacktestHistoryPanelProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <CardTitle>历史结果</CardTitle>
          <span className="text-xs text-muted-foreground">{total} 条</span>
        </div>
        <CardDescription>
          每条结果是一份可复现的输入：同一份参数与行情重跑得到同一组数值。换参数再跑会多一条，
          两条并排即可对比，系统不替你判断谁更好。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">还没有回测记录。</p>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
            {runs.map((run) => (
              <div
                key={run.run_id}
                className={cn(
                  "space-y-3 rounded-lg border p-4",
                  run.run_id === selectedRunId && "ring-2 ring-ring",
                )}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-sm font-medium">{run.inst_id}</span>
                  <span className="flex items-center gap-2">
                    {run.strategy_version_id && versionLabels?.[run.strategy_version_id] ? (
                      <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                        策略版本 {versionLabels[run.strategy_version_id]}
                      </span>
                    ) : null}
                    <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                      {instTypeLabel(run.inst_type)}
                    </span>
                  </span>
                </div>
                <p className="font-mono text-xs text-muted-foreground">
                  {run.start_date} ~ {run.end_date} · {run.bar} · {run.data_source}
                </p>
                <p className="break-words font-mono text-xs text-muted-foreground">
                  参数：{formatParams(run.params)}
                </p>
                {run.metrics ? (
                  <dl className="space-y-1.5">
                    {metricRow("总收益率", `${signedValue(run.metrics.total_return_pct)}%`, true)}
                    {metricRow("最大回撤", `${run.metrics.max_drawdown_pct}%`)}
                    {metricRow("Sharpe", run.metrics.sharpe)}
                    {metricRow("Profit Factor", run.metrics.profit_factor)}
                    {metricRow("交易次数", String(run.metrics.trade_count))}
                  </dl>
                ) : (
                  <p className="text-sm text-muted-foreground">{run.error_message ?? "没有指标"}</p>
                )}
                <div className="flex items-center gap-2">
                  <Button type="button" variant="outline" size="sm" onClick={() => onSelect(run.run_id)}>
                    打开
                  </Button>
                  <Button type="button" variant="ghost" size="sm" onClick={() => onDelete(run.run_id)}>
                    删除
                  </Button>
                  <span className="ml-auto font-mono text-xs text-muted-foreground" title={run.run_id}>
                    {run.run_id.slice(0, 10)}…
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
