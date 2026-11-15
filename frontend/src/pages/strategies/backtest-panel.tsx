import { useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  fetchBacktest,
  type BacktestBatchResponse,
  type BacktestDataSource,
  type BacktestDetailResponse,
  type BacktestRunSummary,
  type StrategyDetail,
  type StrategyVersionDetail,
} from "../../lib/api";
import { dataSourceLabel, versionLabel } from "../../lib/strategies";
import { BacktestDetailPanel } from "../backtests/backtest-detail";
import { BacktestHistoryPanel } from "../backtests/backtest-history";
import { BacktestLaunchForm, Notice } from "./backtest-launch-form";

function messageOf(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

export type StrategyBacktestPanelProps = {
  detail: StrategyDetail;
  versions: StrategyVersionDetail[];
  runs: BacktestRunSummary[];
  runSource: BacktestDataSource;
  onRunSourceChange: (source: BacktestDataSource) => void;
  onLaunched: (batch: BacktestBatchResponse) => void;
  onDeleteRun: (runId: string) => Promise<boolean>;
};

/** 从策略详情发起回测，并复用回测页的历史卡片与详情面板。 */
export function StrategyBacktestPanel({
  detail,
  versions,
  runs,
  runSource,
  onRunSourceChange,
  onLaunched,
  onDeleteRun,
}: StrategyBacktestPanelProps) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<BacktestDetailResponse | null>(null);
  const [runDetailError, setRunDetailError] = useState<string | null>(null);

  const versionNames = Object.fromEntries(
    versions.map((item) => [item.version_id, versionLabel(item.version)]),
  );

  const openRun = (runId: string) => {
    setSelectedRunId(runId);
    setRunDetailError(null);
    fetchBacktest(runId)
      .then(setRunDetail)
      .catch((reason: unknown) => setRunDetailError(messageOf(reason, "回测结果加载失败")));
  };

  const removeRun = async (runId: string) => {
    if (!(await onDeleteRun(runId))) return;
    if (runId === selectedRunId) {
      setSelectedRunId(null);
      setRunDetail(null);
      setRunDetailError(null);
    }
  };

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <CardTitle>发起回测</CardTitle>
          <CardDescription>
            回测绑定选中的不可变版本。周期沿用版本值，标的只能从该版本的标的集合中选择。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <BacktestLaunchForm
            versions={versions}
            initialVersionId={detail.current_version_id}
            runSource={runSource}
            onRunSourceChange={onRunSourceChange}
            onLaunched={(batch) => {
              onLaunched(batch);
              openRun(batch.run_ids[0] ?? batch.run_id);
            }}
            runCount={runs.length}
          />
        </CardContent>
      </Card>

      <BacktestHistoryPanel
        runs={runs}
        total={runs.length}
        selectedRunId={selectedRunId}
        onSelect={openRun}
        onDelete={(runId) => void removeRun(runId)}
        versionLabels={versionNames}
      />

      <p className="text-xs text-muted-foreground">
        回测记录按 {dataSourceLabel(runSource)} 过滤，只显示属于该策略任一个版本的运行。
      </p>

      {runDetailError ? <Notice tone="error">{runDetailError}</Notice> : null}
      {runDetail ? <BacktestDetailPanel detail={runDetail} /> : null}
    </div>
  );
}
