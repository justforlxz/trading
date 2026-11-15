import { RefreshCw } from "lucide-react";

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
import type { StreamLiveness } from "../../lib/stream";
import type { AlertStatusUpdate } from "../../lib/alerts";
import {
  AccountBody,
  ActivityBody,
  AlertsBody,
  MarketBody,
  MarketSummaryBody,
  PositionsBody,
  RiskBody,
  StrategiesBody,
  WatchlistBody,
} from "./cards";
import { ModuleCard, StatusBadge } from "./module-card";

export type OverviewViewProps = {
  summary: DashboardSummary | null;
  error: string | null;
  loading: boolean;
  priceLiveness: StreamLiveness;
  accountLiveness: StreamLiveness;
  pushed: DashboardPushed;
  onRefresh: () => void;
  onResolveAlert?: (alertId: string, status: AlertStatusUpdate) => void;
  resolvingAlertId?: string | null;
};

/** 纯展示组件：测试直接渲染它，不依赖网络、推送连接与浏览器。 */
export function OverviewView({
  summary,
  error,
  loading,
  priceLiveness,
  accountLiveness,
  pushed,
  onRefresh,
  onResolveAlert,
  resolvingAlertId = null,
}: OverviewViewProps) {
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
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">
              {loading ? "正在读取首页汇总…" : "首页汇总不可用，请重试。"}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {summary.degraded.length > 0 ? (
            <p
              role="status"
              className="rounded-md border border-amber-600/40 bg-amber-500/5 px-3 py-2 text-sm text-amber-700 dark:text-amber-400"
            >
              以下模块降级：
              {summary.degraded
                .map((item) => `${moduleTitle(item.module)}（${item.reason}）`)
                .join("；")}
            </p>
          ) : null}

          <ModuleCard
            name="market"
            title="市场概况"
            summary={summary}
            module={summary.market}
            pushedFields={0}
          >
            <MarketBody summary={summary} />
          </ModuleCard>

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
            <Card className="min-w-0" data-module="market_summary" data-status="unavailable">
              <CardContent className="space-y-3 pt-6">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-base font-semibold tracking-tight">市场摘要</h3>
                  <StatusBadge status="unavailable" />
                </div>
                <MarketSummaryBody />
              </CardContent>
            </Card>
          </div>

          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.65fr)_minmax(280px,1fr)]">
            <ModuleCard
              name="watchlist"
              title="关注列表"
              summary={summary}
              module={summary.watchlist}
              pushedFields={Object.keys(pushed.watchlist).length}
              to="/watchlist"
            >
              <WatchlistBody summary={summary} pushed={pushed.watchlist} />
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
    </>
  );
}
