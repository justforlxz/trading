import { useCallback, useEffect, useState } from "react";

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
  fetchBacktests,
  fetchSettings,
  fetchStrategies,
  fetchStrategy,
  fetchStrategyVersions,
  type BacktestBatchResponse,
  type BacktestDataSource,
  type BacktestRunSummary,
  type SettingsResponse,
  type StrategyDetail,
  type StrategySummary,
  type StrategyVersionDetail,
} from "../../lib/api";
import { backtestsForVersions } from "../../lib/strategies";
import { StrategyBacktestPanel } from "./backtest-panel";
import { StrategyDetailPanel } from "./strategy-detail";
import {
  CreateStrategyDialog,
  InstrumentsDialog,
  MetadataDialog,
  NewVersionDialog,
} from "./strategy-form";
import { StrategyListPanel } from "./strategy-list";

type DialogKind = "create" | "metadata" | "version" | "instruments" | null;

export default function StrategiesPage() {
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [strategiesLoading, setStrategiesLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<StrategyDetail | null>(null);
  const [versions, setVersions] = useState<StrategyVersionDetail[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [runs, setRuns] = useState<BacktestRunSummary[]>([]);
  const [runSource, setRunSource] = useState<BacktestDataSource>("okx_spot");
  const [dialog, setDialog] = useState<DialogKind>(null);
  const [error, setError] = useState<string | null>(null);

  const reloadStrategies = useCallback(async () => {
    try {
      setError(null);
      setStrategiesLoading(true);
      const listing = await fetchStrategies();
      setStrategies(listing.items);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "策略列表加载失败");
    } finally {
      setStrategiesLoading(false);
    }
  }, []);

  const applyDetail = useCallback(
    (nextDetail: StrategyDetail, nextVersions: StrategyVersionDetail[], preferred?: string) => {
      setDetail(nextDetail);
      setVersions(nextVersions);
      setSelectedVersionId((current) => {
        if (preferred !== undefined) return preferred;
        if (current !== null && nextVersions.some((item) => item.version_id === current)) {
          return current;
        }
        return nextDetail.current_version_id;
      });
    },
    [],
  );

  const refreshDetail = useCallback(
    async (preferredVersionId?: string) => {
      if (selectedId === null) return;
      try {
        const [nextDetail, nextVersions] = await Promise.all([
          fetchStrategy(selectedId),
          fetchStrategyVersions(selectedId),
        ]);
        applyDetail(nextDetail, nextVersions.items, preferredVersionId);
      } catch (reason: unknown) {
        setError(reason instanceof Error ? reason.message : "策略详情加载失败");
      }
    },
    [applyDetail, selectedId],
  );

  const reloadRuns = useCallback(async (source: BacktestDataSource) => {
    try {
      setError(null);
      const listing = await fetchBacktests(source, 200);
      setRuns(listing.items);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "回测记录加载失败");
    }
  }, []);

  useEffect(() => {
    void reloadStrategies();
  }, [reloadStrategies]);

  useEffect(() => {
    fetchSettings()
      .then(setSettings)
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "设置加载失败");
      });
  }, []);

  useEffect(() => {
    void reloadRuns(runSource);
  }, [reloadRuns, runSource]);

  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      setVersions([]);
      setSelectedVersionId(null);
      return;
    }
    let active = true;
    setError(null);
    Promise.all([fetchStrategy(selectedId), fetchStrategyVersions(selectedId)])
      .then(([nextDetail, nextVersions]) => {
        if (active) applyDetail(nextDetail, nextVersions.items);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : "策略详情加载失败");
        }
      });
    return () => {
      active = false;
    };
  }, [applyDetail, selectedId]);

  const currentVersion =
    detail === null
      ? null
      : (versions.find((version) => version.version_id === detail.current_version_id) ?? null);
  const strategyRuns =
    detail === null ? [] : backtestsForVersions(runs, versions.map((version) => version.version_id));

  const handleDeleteRun = async (runId: string): Promise<boolean> => {
    if (!window.confirm(`删除回测记录 ${runId}？`)) return false;
    setError(null);
    try {
      await deleteBacktest(runId);
      await Promise.all([reloadRuns(runSource), reloadStrategies()]);
      return true;
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "删除回测失败");
      return false;
    }
  };

  return (
    <>
      <PageHeading
        eyebrow="Strategies"
        title="策略与回测"
        description="用户策略、不可变版本、规则 JSON、标的关联与回测记录都来自后端接口。编辑规则会生成新版本，历史回测继续指向生成时的版本。"
      />

      {error ? (
        <p
          role="alert"
          className="mb-6 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive"
        >
          {error}
        </p>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <StrategyListPanel
          items={strategies}
          selectedId={selectedId}
          loading={strategiesLoading}
          onSelect={setSelectedId}
          onCreate={() => setDialog("create")}
        />

        <div className="grid gap-6">
          {detail === null ? (
            <Card>
              <CardHeader>
                <CardTitle>选择一个策略</CardTitle>
                <CardDescription>
                  左侧列表显示当前版本与最近一次回测摘要；选中后可以查看版本目录、规则 JSON、
                  参数、仓位规则与标的集合，并从页面发起回测。
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">还没有选中策略。</p>
              </CardContent>
            </Card>
          ) : (
            <>
              <StrategyDetailPanel
                detail={detail}
                versions={versions}
                selectedVersionId={selectedVersionId}
                onSelectVersion={setSelectedVersionId}
                onEditMetadata={() => setDialog("metadata")}
                onNewVersion={() => setDialog("version")}
                onEditInstruments={() => setDialog("instruments")}
              />
              <StrategyBacktestPanel
                key={settings ? "settings-ready" : "settings-pending"}
                detail={detail}
                versions={versions}
                settings={settings}
                runs={strategyRuns}
                runSource={runSource}
                onRunSourceChange={setRunSource}
                onLaunched={(batch: BacktestBatchResponse) => {
                  void reloadRuns(batch.data_source);
                  void reloadStrategies();
                }}
                onDeleteRun={handleDeleteRun}
              />
            </>
          )}
        </div>
      </div>

      {dialog === "create" ? (
        <CreateStrategyDialog
          onClose={() => setDialog(null)}
          onCreated={(created) => {
            setDialog(null);
            setSelectedId(created.id);
            void reloadStrategies();
          }}
        />
      ) : null}

      {dialog === "metadata" && detail !== null ? (
        <MetadataDialog
          detail={detail}
          onClose={() => setDialog(null)}
          onUpdated={() => {
            setDialog(null);
            void refreshDetail(selectedVersionId ?? undefined);
            void reloadStrategies();
          }}
        />
      ) : null}

      {dialog === "version" && detail !== null && currentVersion !== null ? (
        <NewVersionDialog
          detail={detail}
          current={currentVersion}
          onClose={() => setDialog(null)}
          onCreated={(version) => {
            setDialog(null);
            void refreshDetail(version.version_id);
            void reloadStrategies();
          }}
        />
      ) : null}

      {dialog === "instruments" && detail !== null && currentVersion !== null ? (
        <InstrumentsDialog
          detail={detail}
          current={currentVersion}
          onClose={() => setDialog(null)}
          onUpdated={(version) => {
            setDialog(null);
            void refreshDetail(version.version_id);
            void reloadStrategies();
          }}
        />
      ) : null}
    </>
  );
}
