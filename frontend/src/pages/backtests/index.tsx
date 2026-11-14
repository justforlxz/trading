import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeading } from "../../components/layout/page-parts";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  deleteBacktest,
  fetchBacktest,
  fetchBacktestRanking,
  fetchBacktests,
  type BacktestDataSource,
  type BacktestDetailResponse,
  type BacktestMetric,
  type BacktestRankingResponse,
  type BacktestRunSummary,
} from "../../lib/api";
import { BacktestDetailPanel } from "./backtest-detail";
import { BacktestHistoryPanel } from "./backtest-history";
import { BacktestRankingPanel } from "./backtest-ranking";

/**
 * 回测页：排名 → 历史结果 → 单条结果。
 *
 * 页面只负责取数与组织交互：指标、逐腿贡献、净敞口都由后端算好返回，前端不做派生计算，
 * 也不给任何一条结果贴「最优」标签。
 */
export default function BacktestsPage() {
  const [dataSource, setDataSource] = useState<BacktestDataSource>("okx_spot");
  const [metric, setMetric] = useState<BacktestMetric>("total_return_pct");
  const [runs, setRuns] = useState<BacktestRunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [ranking, setRanking] = useState<BacktestRankingResponse | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BacktestDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const queryRunId = searchParams.get("run");

  const reload = useCallback(
    (source: BacktestDataSource, rankingMetric: BacktestMetric) =>
      Promise.all([fetchBacktests(source), fetchBacktestRanking(source, rankingMetric)]).then(
        ([listing, ranked]) => {
          setRuns(listing.items);
          setTotal(listing.total);
          setRanking(ranked);
        },
      ),
    [],
  );

  useEffect(() => {
    let active = true;
    reload(dataSource, metric).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "回测数据加载失败");
    });
    return () => {
      active = false;
    };
  }, [dataSource, metric, reload]);

  const openDetail = useCallback((runId: string) => {
    setError(null);
    fetchBacktest(runId)
      .then((value) => {
        setDetail(value);
        setSelectedRunId(value.run.run_id);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "回测结果加载失败");
      });
  }, []);

  useEffect(() => {
    if (queryRunId === null) return;
    openDetail(queryRunId);
  }, [queryRunId, openDetail]);

  const remove = (runId: string) => {
    if (!window.confirm(`删除回测记录 ${runId}？`)) return;
    setError(null);
    deleteBacktest(runId)
      .then(() => {
        if (selectedRunId === runId) {
          setSelectedRunId(null);
          setDetail(null);
        }
        return reload(dataSource, metric);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "删除失败");
      });
  };

  return (
    <>
      <PageHeading
        eyebrow="Backtests"
        title="回测"
        description="查看已保存的回测结果：按指标排序、按标的逐条打开，数值全部来自后端。按策略版本发起回测在 B7 交付。"
      />

      {error ? (
        <p className="mb-6 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <div className="grid gap-6">
        <label className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">数据源</span>
          <select
            className="h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            value={dataSource}
            onChange={(event) => setDataSource(event.target.value as BacktestDataSource)}
          >
            <option value="okx_spot">OKX 现货（okx_spot）</option>
            <option value="okx_swap">OKX 永续（okx_swap）</option>
            <option value="us_equity_proxy">美股代理（us_equity_proxy）</option>
            <option value="okx">未区分形态的旧数据（okx）</option>
          </select>
          <span className="text-xs text-muted-foreground">只影响读取哪些已保存的结果，不做跨源聚合。</span>
        </label>

        <Card>
          <CardHeader>
            <CardTitle>发起回测</CardTitle>
            <CardDescription>
              旧策略实例接口已由 B6 删除；按策略版本发起的回测在 B7 与 S4-3 交付。历史结果、
              排名与单条详情仍可查看。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              当前页只读：不能新建回测，已保存的结果不受影响。
            </p>
          </CardContent>
        </Card>

        <BacktestRankingPanel
          ranking={ranking}
          metric={metric}
          selectedRunId={selectedRunId}
          onMetricChange={setMetric}
        />

        <BacktestHistoryPanel
          runs={runs}
          total={total}
          selectedRunId={selectedRunId}
          onSelect={openDetail}
          onDelete={remove}
        />

        {detail ? <BacktestDetailPanel detail={detail} /> : null}
      </div>
    </>
  );
}
