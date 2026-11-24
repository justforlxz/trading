import { Pencil, RefreshCw } from "lucide-react";
import { useState } from "react";

import { PageHeading } from "../../components/layout/page-parts";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { StreamNotice } from "../../components/ui/stream-status";
import {
  asOfText,
  moduleTitle,
  type DashboardPushed,
  type DashboardSummary,
} from "../../lib/dashboard";
import type { MacroOverviewResponse } from "../../lib/api";
import type { AiSummary, MarketSnapshot } from "../../lib/market";
import type { StreamLiveness } from "../../lib/stream";
import type { AlertStatusUpdate } from "../../lib/alerts";
import { pinnedCardRows, pinnedCountText, type PinnedCandidate } from "../../lib/home-pinned";
import {
  AccountBody,
  ActivityBody,
  AlertsBody,
  PositionsBody,
  RiskBody,
  StrategiesBody,
  WatchlistBody,
} from "./cards";
import { MarketOverviewCard, MarketSummaryCard } from "./market-cards";
import { ModuleCard } from "./module-card";
import { WatchlistPicker } from "./watchlist-picker";

export type OverviewViewProps = {
  summary: DashboardSummary | null;
  error: string | null;
  loading: boolean;
  priceLiveness: StreamLiveness;
  accountLiveness: StreamLiveness;
  pushed: DashboardPushed;
  marketOverview: MarketSnapshot | null;
  marketOverviewError: string | null;
  marketOverviewLoading: boolean;
  macroOverview: MacroOverviewResponse | null;
  macroOverviewError: string | null;
  macroOverviewLoading: boolean;
  aiSummary: AiSummary | null;
  aiSummaryError: string | null;
  aiSummaryLoading: boolean;
  onRefresh: () => void;
  onResolveAlert?: (alertId: string, status: AlertStatusUpdate) => void;
  resolvingAlertId?: string | null;
  /** 首页关注列表置顶的标的（服务端 `display.homepage_pinned`），按选择顺序。 */
  pinnedWatchlist: string[];
  /** 整份自选（`GET /api/watchlist`）：弹窗的候选，不受首页汇总五行上限的影响。 */
  watchlistCandidates: PinnedCandidate[];
  /** 保存置顶清单；失败时抛错，由弹窗自己显示原因并保持打开。 */
  onSavePinned: (next: string[]) => Promise<void>;
};

/** 纯展示组件：测试直接渲染它，不依赖网络、推送连接与浏览器。 */
export function OverviewView({
  summary,
  error,
  loading,
  priceLiveness,
  accountLiveness,
  pushed,
  marketOverview,
  marketOverviewError,
  marketOverviewLoading,
  macroOverview,
  macroOverviewError,
  macroOverviewLoading,
  aiSummary,
  aiSummaryError,
  aiSummaryLoading,
  onRefresh,
  onResolveAlert,
  resolvingAlertId = null,
  pinnedWatchlist,
  watchlistCandidates,
  onSavePinned,
}: OverviewViewProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  // 卡片行 = 置顶清单 ∩ 当前自选，价格用首页汇总里更实时的那一份覆盖。
  // 不能直接拿汇总里的行：汇总只带五行，置顶到第 6 个标的上会保存成功却渲染不出来。
  const pinnedRows = pinnedCardRows(
    watchlistCandidates,
    summary?.watchlist.data?.items ?? [],
    pinnedWatchlist,
  );
  // 推送覆盖数只算卡片上真的显示出来的行：没置顶时卡片是空的，写「5 条记录含推送
  // 字段」会让人以为卡里还有 5 行。
  const pinnedRowIds = new Set(pinnedRows.map((item) => item.inst_id));
  const pushedPinnedRows = Object.keys(pushed.watchlist).filter((instId) =>
    pinnedRowIds.has(instId),
  ).length;
  const degraded = summary?.degraded.filter((item) => item.module !== "market") ?? [];
  const marketOverviewCard = (
    <MarketOverviewCard
      overview={marketOverview}
      error={marketOverviewError}
      loading={marketOverviewLoading}
      macro={macroOverview}
      macroError={macroOverviewError}
      macroLoading={macroOverviewLoading}
    />
  );
  const marketSummaryCard = (
    <MarketSummaryCard
      summary={aiSummary}
      dataAsOf={marketOverview?.as_of ?? null}
      error={aiSummaryError}
      loading={aiSummaryLoading}
    />
  );
  return (
    <>
      <PageHeading
        eyebrow="Trading overview"
        title="市场与账户"
        description="一屏查看市场、账户、风险、持仓、自选、提醒与策略；每个模块独立降级，数值全部来自后端。"
        actions={
          <>
            <span className="text-xs text-muted-foreground">
              {summary === null ? "尚未取到汇总" : `汇总时间 ${asOfText(summary.as_of)}`}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onRefresh}
              disabled={loading}
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              {loading ? "刷新中…" : "刷新"}
            </Button>
          </>
        }
      />

      {error ? (
        <p
          role="alert"
          className="mb-4 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive"
        >
          {error}
        </p>
      ) : null}

      <div className="mb-4 space-y-2">
        <StreamNotice liveness={priceLiveness} subject="关注列表价格" />
        <StreamNotice liveness={accountLiveness} subject="账户与持仓快照" />
      </div>

      {summary === null ? (
        <div className="grid gap-4">
          {marketOverviewCard}
          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">
                {loading ? "正在读取首页汇总…" : "首页汇总不可用，请重试。"}
              </p>
            </CardContent>
          </Card>
          {marketSummaryCard}
        </div>
      ) : (
        <div className="grid gap-4">
          {degraded.length > 0 ? (
            <p
              role="status"
              className="rounded-md border border-amber-600/40 bg-amber-500/5 px-3 py-2 text-sm text-amber-700 dark:text-amber-400"
            >
              以下模块降级：
              {degraded
                .map((item) => `${moduleTitle(item.module)}（${item.reason}）`)
                .join("；")}
            </p>
          ) : null}

          {marketOverviewCard}

          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(280px,1fr)]">
            <ModuleCard
              name="account"
              title="账户概览"
              summary={summary}
              module={summary.account}
              pushedFields={pushed.account === null ? 0 : 1}
              to="/positions"
            >
              <AccountBody summary={summary} pushedAt={pushed.account} />
            </ModuleCard>
            <ModuleCard
              name="risk"
              title="风险监控"
              summary={summary}
              module={summary.risk}
              pushedFields={0}
              to="/positions"
            >
              <RiskBody summary={summary} />
            </ModuleCard>
          </div>

          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.65fr)_minmax(280px,1fr)]">
            <ModuleCard
              name="positions"
              title="当前持仓"
              summary={summary}
              module={summary.positions}
              pushedFields={Object.keys(pushed.positions).length}
              to="/positions"
            >
              <PositionsBody summary={summary} pushed={pushed.positions} />
            </ModuleCard>
            {marketSummaryCard}
          </div>

          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.65fr)_minmax(280px,1fr)]">
            <ModuleCard
              name="watchlist"
              title="关注列表"
              summary={summary}
              module={summary.watchlist}
              pushedFields={pushedPinnedRows}
              to="/watchlist"
              meta={pinnedCountText(pinnedRows.length)}
              actions={
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground"
                  onClick={() => setPickerOpen(true)}
                  disabled={summary.watchlist.data == null}
                >
                  <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                  编辑
                </Button>
              }
            >
              <WatchlistBody
                summary={summary}
                pushed={pushed.watchlist}
                rows={pinnedRows}
                onEdit={() => setPickerOpen(true)}
              />
            </ModuleCard>
            <ModuleCard
              name="alerts"
              title="提醒"
              summary={summary}
              module={summary.alerts}
              pushedFields={0}
              to="/journal"
            >
              <AlertsBody
                summary={summary}
                onResolve={onResolveAlert}
                resolvingId={resolvingAlertId}
              />
            </ModuleCard>
          </div>

          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
            <ModuleCard
              name="strategies"
              title="策略运行"
              summary={summary}
              module={summary.strategies}
              pushedFields={0}
              to="/strategies"
            >
              <StrategiesBody summary={summary} />
            </ModuleCard>
            <ModuleCard
              name="activity"
              title="最近活动"
              summary={summary}
              module={summary.activity}
              pushedFields={0}
              to="/journal"
            >
              <ActivityBody summary={summary} />
            </ModuleCard>
          </div>
        </div>
      )}

      <WatchlistPicker
        open={pickerOpen}
        items={watchlistCandidates}
        pinned={pinnedWatchlist}
        onClose={() => setPickerOpen(false)}
        onSave={onSavePinned}
      />
    </>
  );
}
