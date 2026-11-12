import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { BacktestMetric, BacktestRankingResponse } from "../../lib/api";
import { instTypeLabel, signedTone, signedValue } from "../../lib/display";
import { cn } from "../../lib/utils";
import { formatParams } from "./format";

const METRICS: Array<{ value: BacktestMetric; label: string }> = [
  { value: "total_return_pct", label: "总收益率（从高到低）" },
  { value: "max_drawdown_pct", label: "最大回撤（从低到高）" },
  { value: "sharpe", label: "Sharpe（从高到低）" },
  { value: "profit_factor", label: "Profit Factor（从高到低）" },
];

const SELECT_CLASS =
  "h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

export type BacktestRankingPanelProps = {
  ranking: BacktestRankingResponse | null;
  metric: BacktestMetric;
  selectedRunId: string | null;
  onMetricChange: (metric: BacktestMetric) => void;
};

/**
 * 排行榜：按一个指标排序的历史结果，只排序、不标「最优」。
 *
 * 名次由当前选中的那一个指标决定，不引入第二把尺子；后端也不会为任何一行加上
 * 「推荐」标记，谁能用由人自己判断。
 */
export function BacktestRankingPanel({
  ranking,
  metric,
  selectedRunId,
  onMetricChange,
}: BacktestRankingPanelProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <CardTitle>排名</CardTitle>
          <select
            className={SELECT_CLASS}
            value={metric}
            onChange={(event) => onMetricChange(event.target.value as BacktestMetric)}
          >
            {METRICS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
        <CardDescription>
          只按选中的这一个指标排序，不设「最优」结论；回撤是正数幅度，按它排序时最小的在最前。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!ranking || ranking.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">该数据源还没有回测结果。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">标的</th>
                  <th className="py-2 pr-3 font-medium">参数</th>
                  <th className="py-2 pr-3 font-medium">总收益率</th>
                  <th className="py-2 pr-3 font-medium">最大回撤</th>
                  <th className="py-2 pr-3 font-medium">Sharpe</th>
                  <th className="py-2 pr-3 font-medium">Profit Factor</th>
                  <th className="py-2 font-medium">交易次数</th>
                </tr>
              </thead>
              <tbody>
                {ranking.items.map((row, index) => (
                  <tr
                    key={row.run_id}
                    className={cn(
                      "border-b last:border-b-0",
                      index === 0 && "bg-muted/40",
                    )}
                  >
                    <td className="py-2 pr-3">
                      <span className="font-medium">{row.inst_id}</span>
                      <span className="ml-2 rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                        {instTypeLabel(row.inst_type)}
                      </span>
                      <div className="mt-0.5 font-mono text-xs text-muted-foreground" title={row.run_id}>
                        {row.run_id.slice(0, 10)}…
                      </div>
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">
                      {formatParams(row.params)}
                    </td>
                    <td className={cn("py-2 pr-3 font-mono tabular-nums", signedTone(row.total_return_pct))}>
                      {signedValue(row.total_return_pct)}%
                    </td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{row.max_drawdown_pct}%</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{row.sharpe}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{row.profit_factor}</td>
                    <td className="py-2 font-mono tabular-nums">{row.trade_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {selectedRunId === null ? null : (
              <p className="mt-3 text-xs text-muted-foreground">
                排行榜是每次都按最新结果重算的排序视图；要看某一次的完整结果，在下面的历史结果里打开它。
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
