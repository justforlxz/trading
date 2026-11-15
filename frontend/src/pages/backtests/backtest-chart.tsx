import { CandlestickChart } from "../../components/chart/candlestick-chart";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { BacktestChartResponse } from "../../lib/api";
import { backtestChartInput, chartMarkerCounts } from "../../lib/backtest-detail";

export type BacktestChartPanelProps = {
  chart: BacktestChartResponse | null;
  loading: boolean;
  error: string | null;
};

/**
 * 回测 K 线与成交标记。
 *
 * 标记只来自 `GET /backtests/{run_id}/chart` 的 `markers`，每个标记对应一笔已保存交易
 * 的入场或出场；没有对应 K 线的标记不绘制，也不插值到相邻 K 线。
 */
export function BacktestChartPanel({ chart, loading, error }: BacktestChartPanelProps) {
  const input = chart === null ? null : backtestChartInput(chart);
  const counts = chart === null ? null : chartMarkerCounts(chart);

  return (
    <Card>
      <CardHeader>
        <CardTitle>K 线与进出场标记</CardTitle>
        <CardDescription>
          {chart === null
            ? "读取本次回测保存的 K 线与成交标记。"
            : `${chart.inst_id} · ${chart.bar} · 数据源 ${chart.data_source} · ${chart.candles.length} 根 K 线 · 入场 ${counts?.entries ?? 0} 个、出场 ${counts?.exits ?? 0} 个标记`}
          {counts !== null && counts.unmatched > 0
            ? ` · ${counts.unmatched} 个标记没有对应 K 线，未绘制`
            : ""}
        </CardDescription>
        <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="inline-block size-0 border-x-[5px] border-b-[8px] border-x-transparent border-b-emerald-600 dark:border-b-emerald-400" />
            买入入场
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block size-0 border-x-[5px] border-t-[8px] border-x-transparent border-t-rose-600 dark:border-t-rose-400" />
            卖出入场
          </span>
          <span>实心为入场，空心为出场；悬停标记可看数量、价格、盈亏与退出原因。</span>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <p className="py-12 text-center text-sm text-muted-foreground">正在读取图表数据…</p>
        ) : error !== null ? (
          <p className="py-12 text-center text-sm text-destructive">{error}</p>
        ) : input === null || input.candles.length === 0 ? (
          <p className="py-12 text-center text-sm text-muted-foreground">
            这次回测没有保存可绘制的 K 线。
          </p>
        ) : (
          <CandlestickChart data={input} label="回测 K 线与成交标记" />
        )}
      </CardContent>
    </Card>
  );
}
