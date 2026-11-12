import { useCallback, useEffect, useState } from "react";

import { PageHeading } from "../../components/layout/page-parts";
import {
  createBacktest,
  deleteBacktest,
  fetchBacktest,
  fetchBacktestRanking,
  fetchBacktests,
  fetchStrategyInstances,
  type BacktestDataSource,
  type BacktestDetailResponse,
  type BacktestMetric,
  type BacktestRankingResponse,
  type BacktestRequest,
  type BacktestRunSummary,
  type StrategyInstance,
} from "../../lib/api";
import { BacktestDetailPanel } from "./backtest-detail";
import { BacktestForm } from "./backtest-form";
import { BacktestHistoryPanel } from "./backtest-history";
import { BacktestRankingPanel } from "./backtest-ranking";

/**
 * 回测页：发起 → 排名 → 历史结果 → 单条结果。
 *
 * 页面只负责取数与组织交互：指标、逐腿贡献、净敞口都由后端算好返回，前端不做派生计算，
 * 也不给任何一条结果贴「最优」标签。
 */
export default function BacktestsPage() {
  const [instances, setInstances] = useState<StrategyInstance[]>([]);
  const [instanceId, setInstanceId] = useState<string | null>(null);
  const [dataSource, setDataSource] = useState<BacktestDataSource>("okx_spot");
  const [metric, setMetric] = useState<BacktestMetric>("total_return_pct");
  const [runs, setRuns] = useState<BacktestRunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [ranking, setRanking] = useState<BacktestRankingResponse | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BacktestDetailResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchStrategyInstances()
      .then((listing) => {
        if (!active) return;
        setInstances(listing.items);
        setInstanceId((current) => current ?? listing.items[0]?.instance_id ?? null);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "策略实例加载失败");
      });
    return () => {
      active = false;
    };
  }, []);

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

  const openDetail = (runId: string) => {
    setBusy(true);
    setError(null);
    fetchBacktest(runId)
      .then((value) => {
        setDetail(value);
        setSelectedRunId(value.run.run_id);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "回测结果加载失败");
      })
      .finally(() => setBusy(false));
  };

  const submit = (request: BacktestRequest) => {
    setBusy(true);
    setError(null);
    createBacktest(request)
      .then((created) => {
        setDataSource(request.data_source);
        return reload(request.data_source, metric).then(() => created);
      })
      .then((created) => openDetail(created.run_id))
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "回测失败");
      })
      .finally(() => setBusy(false));
  };

  const remove = (runId: string) => {
    if (!window.confirm(`删除回测记录 ${runId}？`)) return;
    setBusy(true);
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
      })
      .finally(() => setBusy(false));
  };

  return (
    <>
      <PageHeading
        eyebrow="Backtests"
        title="回测"
        description="选策略实例与标的集合，设成本与资金，跑批量回测；结果按标的各一条，可排序、可逐腿回放，同一份请求重跑得到同一组数值。"
      />

      {error ? (
        <p className="mb-6 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <div className="grid gap-6">
        <BacktestForm
          instances={instances}
          instanceId={instanceId}
          dataSource={dataSource}
          busy={busy}
          onInstanceChange={setInstanceId}
          onDataSourceChange={setDataSource}
          onSubmit={submit}
        />

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
