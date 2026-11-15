import { LineChart } from "../../components/chart/line-chart";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { BacktestDetailResponse, BacktestEquityResponse } from "../../lib/api";
import { drawdownLinePoints, equityLinePoints } from "../../lib/backtest-detail";

export type BacktestEquityPanelProps = {
  detail: BacktestDetailResponse;
  equity: BacktestEquityResponse | null;
  loading: boolean;
  error: string | null;
};

/**
 * 净值与回撤。
 *
 * 两条折线都直接来自 `GET /backtests/{run_id}/equity`：上图为策略净值，下图为回撤。
 * 基准净值未随回测保存时接口返回 `null`，页面明确写「未保存」，不补一条假基准。
 */
export function BacktestEquityPanel({
  detail,
  equity,
  loading,
  error,
}: BacktestEquityPanelProps) {
  const points = equity?.points ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>净值与回撤</CardTitle>
        <CardDescription>
          回测区间 {detail.request.start_date} ~ {detail.request.end_date} · 数据源{" "}
          {detail.request.data_source} · {detail.request.bar}
          {equity === null ? "" : ` · 共 ${points.length} 个点`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {loading ? (
          <p className="py-10 text-center text-sm text-muted-foreground">正在读取净值序列…</p>
        ) : error !== null ? (
          <p className="py-10 text-center text-sm text-destructive">{error}</p>
        ) : equity === null || points.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            这次回测没有保存净值序列。
          </p>
        ) : (
          <>
            <div>
              <p className="mb-1 text-xs text-muted-foreground">策略净值</p>
              <LineChart
                points={equityLinePoints(points)}
                label="策略净值"
                emptyText="没有可画的净值点。"
              />
            </div>
            <div>
              <p className="mb-1 text-xs text-muted-foreground">
                回撤（%，相对前期最高净值；0 表示没有回撤）
              </p>
              <LineChart
                points={drawdownLinePoints(points)}
                label="回撤"
                emptyText="没有可画的回撤点。"
              />
            </div>
            <p className="text-xs text-muted-foreground">
              {equity.benchmark === null
                ? "本次回测没有保存基准净值，因此不绘制基准曲线。"
                : `基准净值：${equity.benchmark}`}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
