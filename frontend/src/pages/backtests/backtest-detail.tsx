import { useEffect, useState } from "react";

import {
  fetchBacktestChart,
  fetchBacktestEquity,
  fetchBacktestReplay,
  type BacktestChartResponse,
  type BacktestDetailResponse,
  type BacktestEquityResponse,
  type BacktestReplayResponse,
} from "../../lib/api";
import { BacktestChartPanel } from "./backtest-chart";
import { BacktestEquityPanel } from "./backtest-equity";
import { BacktestReplayPanel } from "./backtest-replay";
import { BacktestLegs } from "./backtest-legs";
import { BacktestSummary } from "./backtest-summary";
import { BacktestTrades } from "./backtest-trades";

export type BacktestDetailPanelProps = {
  detail: BacktestDetailResponse;
};

function messageOf(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

/**
 * 单条回测的完整详情：概要指标、K 线与成交标记、净值与回撤、历史回放、逐腿明细、
 * 可筛选并导出的交易明细。
 *
 * 页面不重算任何指标：图表、净值、回撤、回放与交易都直接来自后端已保存的结果；
 * 回放只在取回一次的内存序列里移动，不请求实时行情。
 */
export function BacktestDetailPanel({ detail }: BacktestDetailPanelProps) {
  const runId = detail.run.run_id;
  const [chart, setChart] = useState<BacktestChartResponse | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const [equity, setEquity] = useState<BacktestEquityResponse | null>(null);
  const [equityError, setEquityError] = useState<string | null>(null);
  const [replay, setReplay] = useState<BacktestReplayResponse | null>(null);
  const [replayError, setReplayError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setChart(null);
    setChartError(null);
    setEquity(null);
    setEquityError(null);
    setReplay(null);
    setReplayError(null);

    Promise.allSettled([
      fetchBacktestChart(runId),
      fetchBacktestEquity(runId),
      fetchBacktestReplay(runId),
    ]).then(([chartResult, equityResult, replayResult]) => {
      if (!active) return;
      if (chartResult.status === "fulfilled") setChart(chartResult.value);
      else setChartError(messageOf(chartResult.reason, "K 线加载失败"));
      if (equityResult.status === "fulfilled") setEquity(equityResult.value);
      else setEquityError(messageOf(equityResult.reason, "净值加载失败"));
      if (replayResult.status === "fulfilled") setReplay(replayResult.value);
      else setReplayError(messageOf(replayResult.reason, "回放加载失败"));
      setLoading(false);
    });

    return () => {
      active = false;
    };
  }, [runId]);

  return (
    <div className="grid gap-6">
      <BacktestSummary detail={detail} />
      <BacktestChartPanel chart={chart} loading={loading} error={chartError} />
      <BacktestEquityPanel
        detail={detail}
        equity={equity}
        loading={loading}
        error={equityError}
      />
      <BacktestReplayPanel replay={replay} loading={loading} error={replayError} />
      <BacktestLegs legs={detail.legs} />
      <BacktestTrades runId={runId} />
    </div>
  );
}
