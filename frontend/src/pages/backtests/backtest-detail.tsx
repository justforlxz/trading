import { LineChart } from "../../components/chart/line-chart";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { BacktestDetailResponse } from "../../lib/api";
import { BacktestLegs } from "./backtest-legs";
import { BacktestSummary } from "./backtest-summary";
import { BacktestTrades } from "./backtest-trades";

export type BacktestDetailPanelProps = {
  detail: BacktestDetailResponse;
};

/**
 * 单条回测的结果：组合级汇总在上，资金曲线、逐腿明细与逐笔交易在下面。
 *
 * 资金曲线用「卡片 + 单条折线」表达：不画 K 线、不做多窗格联动。页面不重算任何指标，
 * 全部数值来自后端。
 */
export function BacktestDetailPanel({ detail }: BacktestDetailPanelProps) {
  const curve = detail.equity_curve;
  const points = curve.map((point) => ({ time: point.time, price: point.equity }));

  return (
    <div className="grid gap-6">
      <BacktestSummary detail={detail} />

      <Card>
        <CardHeader>
          <CardTitle>资金曲线</CardTitle>
          <CardDescription>
            逐 bar 净值，共 {curve.length} 个点；只画一条线，不叠加其他指标。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <LineChart points={points} label="资金曲线" emptyText="这次回测没有资金曲线。" />
        </CardContent>
      </Card>

      <BacktestLegs legs={detail.legs} />
      <BacktestTrades trades={detail.trades} />
    </div>
  );
}
