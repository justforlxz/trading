import { useEffect, useState, type FormEvent } from "react";

import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  createBacktest,
  fetchBacktest,
  type BacktestBatchResponse,
  type BacktestCosts,
  type BacktestDataSource,
  type BacktestDetailResponse,
  type BacktestRunSummary,
  type SettingsResponse,
  type StrategyDetail,
  type StrategyVersionDetail,
} from "../../lib/api";
import {
  BACKTEST_DATA_SOURCE_OPTIONS,
  EXECUTION_MODEL_OPTIONS,
  dataSourceLabel,
  directionLabel,
  versionLabel,
  type ExecutionModel,
} from "../../lib/strategies";
import { cn } from "../../lib/utils";
import { BacktestDetailPanel } from "../backtests/backtest-detail";
import { BacktestHistoryPanel } from "../backtests/backtest-history";

const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";
const LABEL_CLASS = "space-y-1.5 text-sm";

type LaunchFields = {
  startDate: string;
  endDate: string;
  initialCapital: string;
  positionSize: string;
  maxPositionPct: string;
  quoteCurrency: string;
  fundingEnabled: boolean;
  executionModel: ExecutionModel;
  costs: BacktestCosts;
};

function launchFieldsFrom(settings: SettingsResponse | null): LaunchFields {
  return {
    startDate: "",
    endDate: "",
    initialCapital: settings?.backtest.default_initial_capital ?? "",
    positionSize: "",
    maxPositionPct: "",
    quoteCurrency: "USDT",
    fundingEnabled: settings?.backtest.funding_enabled ?? true,
    executionModel: "next_open",
    costs: settings
      ? { ...settings.costs }
      : { maker_fee_bps: "", taker_fee_bps: "", slippage_bps: "", spread_bps: "" },
  };
}

function messageOf(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function Notice({ tone, children }: { tone: "error" | "info"; children: string }) {
  return (
    <p
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "rounded-md border px-3 py-2 text-sm",
        tone === "error" ? "border-destructive/40 text-destructive" : "text-muted-foreground",
      )}
    >
      {children}
    </p>
  );
}

export type StrategyBacktestPanelProps = {
  detail: StrategyDetail;
  versions: StrategyVersionDetail[];
  settings: SettingsResponse | null;
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
  settings,
  runs,
  runSource,
  onRunSourceChange,
  onLaunched,
  onDeleteRun,
}: StrategyBacktestPanelProps) {
  const [versionId, setVersionId] = useState(detail.current_version_id);
  const [selectedInstruments, setSelectedInstruments] = useState<string[]>([]);
  const [fields, setFields] = useState<LaunchFields>(() => launchFieldsFrom(settings));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<BacktestDetailResponse | null>(null);
  const [runDetailError, setRunDetailError] = useState<string | null>(null);

  const version = versions.find((item) => item.version_id === versionId) ?? null;
  const versionNames = Object.fromEntries(
    versions.map((item) => [item.version_id, versionLabel(item.version)]),
  );

  useEffect(() => {
    setVersionId(detail.current_version_id);
  }, [detail.id, detail.current_version_id]);

  useEffect(() => {
    setSelectedInstruments(version ? [...version.instrument_ids] : []);
  }, [version]);

  const update = (patch: Partial<LaunchFields>) =>
    setFields((current) => ({ ...current, ...patch }));

  const updateCost = (key: keyof BacktestCosts, value: string) =>
    setFields((current) => ({ ...current, costs: { ...current.costs, [key]: value } }));

  const toggleInstrument = (instId: string, checked: boolean) =>
    setSelectedInstruments((current) =>
      checked ? [...current, instId] : current.filter((item) => item !== instId),
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

  const ready =
    version !== null &&
    selectedInstruments.length > 0 &&
    fields.startDate !== "" &&
    fields.endDate !== "" &&
    fields.initialCapital.trim() !== "" &&
    fields.positionSize.trim() !== "" &&
    fields.maxPositionPct.trim() !== "" &&
    fields.costs.maker_fee_bps.trim() !== "" &&
    fields.costs.taker_fee_bps.trim() !== "" &&
    fields.costs.slippage_bps.trim() !== "" &&
    fields.costs.spread_bps.trim() !== "" &&
    fields.quoteCurrency.trim() !== "";

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready || version === null || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const batch = await createBacktest({
        strategy_version_id: version.version_id,
        targets: { mode: "list", inst_ids: selectedInstruments, group: null },
        bar: version.timeframe,
        start_date: fields.startDate,
        end_date: fields.endDate,
        initial_capital: fields.initialCapital.trim(),
        quote_currency: fields.quoteCurrency.trim(),
        position_size: fields.positionSize.trim(),
        max_position_pct: fields.maxPositionPct.trim(),
        costs: fields.costs,
        funding_enabled: fields.fundingEnabled,
        execution_model: fields.executionModel,
        data_source: runSource,
      });
      setNotice(
        `已创建 ${batch.run_ids.length} 条回测记录；等权组合净值由接口返回，页面不做二次计算。`,
      );
      onLaunched(batch);
      openRun(batch.run_ids[0] ?? batch.run_id);
    } catch (reason: unknown) {
      setError(messageOf(reason, "发起回测失败"));
    } finally {
      setBusy(false);
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
          <form className="grid gap-4" onSubmit={(event) => void submit(event)}>
            {error ? <Notice tone="error">{error}</Notice> : null}
            {notice ? <Notice tone="info">{notice}</Notice> : null}

            <div className="grid gap-4 sm:grid-cols-2">
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">策略版本</span>
                <select
                  className={INPUT_CLASS}
                  value={versionId}
                  onChange={(event) => setVersionId(event.target.value)}
                >
                  {versions.map((item) => (
                    <option key={item.version_id} value={item.version_id}>
                      {versionLabel(item.version)} · {item.timeframe} ·{" "}
                      {directionLabel(item.direction)} · {item.version_id}
                    </option>
                  ))}
                </select>
              </label>
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">数据源（发起与记录筛选共用）</span>
                <select
                  className={INPUT_CLASS}
                  value={runSource}
                  onChange={(event) =>
                    onRunSourceChange(event.target.value as BacktestDataSource)
                  }
                >
                  {BACKTEST_DATA_SOURCE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <fieldset className="space-y-2">
              <legend className="text-sm text-muted-foreground">回测标的（来自版本标的集合）</legend>
              {version === null || version.instrument_ids.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  该版本还没有标的。先在「调整标的」里补充标的。
                </p>
              ) : (
                <ul className="flex flex-wrap gap-2">
                  {version.instrument_ids.map((instId) => (
                    <li key={instId}>
                      <label className="flex items-center gap-2 rounded-full border px-3 py-1 text-xs">
                        <input
                          type="checkbox"
                          checked={selectedInstruments.includes(instId)}
                          onChange={(event) => toggleInstrument(instId, event.target.checked)}
                        />
                        <span className="font-mono">{instId}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </fieldset>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">开始日期</span>
                <input
                  type="date"
                  className={INPUT_CLASS}
                  value={fields.startDate}
                  onChange={(event) => update({ startDate: event.target.value })}
                  required
                />
              </label>
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">结束日期</span>
                <input
                  type="date"
                  className={INPUT_CLASS}
                  value={fields.endDate}
                  onChange={(event) => update({ endDate: event.target.value })}
                  required
                />
              </label>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">初始资金</span>
                <input
                  className={INPUT_CLASS}
                  inputMode="decimal"
                  value={fields.initialCapital}
                  onChange={(event) => update({ initialCapital: event.target.value })}
                  required
                />
              </label>
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">单标的投入上限（计价货币）</span>
                <input
                  className={INPUT_CLASS}
                  inputMode="decimal"
                  value={fields.positionSize}
                  onChange={(event) => update({ positionSize: event.target.value })}
                  required
                />
              </label>
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">单标的仓位上限（0 到 1 的比例）</span>
                <input
                  className={INPUT_CLASS}
                  inputMode="decimal"
                  value={fields.maxPositionPct}
                  onChange={(event) => update({ maxPositionPct: event.target.value })}
                  required
                />
              </label>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">挂单手续费（bps）</span>
                <input
                  className={INPUT_CLASS}
                  inputMode="decimal"
                  value={fields.costs.maker_fee_bps}
                  onChange={(event) => updateCost("maker_fee_bps", event.target.value)}
                  required
                />
              </label>
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">吃单手续费（bps）</span>
                <input
                  className={INPUT_CLASS}
                  inputMode="decimal"
                  value={fields.costs.taker_fee_bps}
                  onChange={(event) => updateCost("taker_fee_bps", event.target.value)}
                  required
                />
              </label>
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">滑点（bps）</span>
                <input
                  className={INPUT_CLASS}
                  inputMode="decimal"
                  value={fields.costs.slippage_bps}
                  onChange={(event) => updateCost("slippage_bps", event.target.value)}
                  required
                />
              </label>
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">买卖价差（bps）</span>
                <input
                  className={INPUT_CLASS}
                  inputMode="decimal"
                  value={fields.costs.spread_bps}
                  onChange={(event) => updateCost("spread_bps", event.target.value)}
                  required
                />
              </label>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">计价货币</span>
                <input
                  className={INPUT_CLASS}
                  value={fields.quoteCurrency}
                  onChange={(event) => update({ quoteCurrency: event.target.value })}
                  required
                />
              </label>
              <label className={LABEL_CLASS}>
                <span className="text-muted-foreground">执行模型</span>
                <select
                  className={INPUT_CLASS}
                  value={fields.executionModel}
                  onChange={(event) =>
                    update({ executionModel: event.target.value as ExecutionModel })
                  }
                >
                  {EXECUTION_MODEL_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 self-end rounded-md border px-3 py-2 text-sm">
                <input
                  type="checkbox"
                  checked={fields.fundingEnabled}
                  onChange={(event) => update({ fundingEnabled: event.target.checked })}
                />
                <span>永续计入资金费</span>
              </label>
            </div>

            <p className="rounded-md border px-3 py-2 text-xs text-muted-foreground">
              将使用{" "}
              {version === null
                ? "（尚未选择版本）"
                : `${versionLabel(version.version)}（${version.version_id}），周期 ${version.timeframe}，区间 ${fields.startDate || "（未填开始日期）"} ~ ${fields.endDate || "（未填结束日期）"}，数据源 ${runSource}`}
              。该描述与提交的请求一致，便于回看时确认用的是哪一版。
            </p>

            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted-foreground">{runs.length} 条该策略回测记录</span>
              <Button type="submit" disabled={!ready || busy}>
                {busy ? "提交中…" : "发起回测"}
              </Button>
            </div>
          </form>
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
