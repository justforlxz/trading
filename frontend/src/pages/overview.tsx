import { useEffect, useState, type ReactNode } from "react";

import { LineChart } from "../components/chart/line-chart";
import { PageHeading } from "../components/layout/page-parts";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import {
  fetchOverview,
  type OverviewMarketSnapshot,
  type OverviewMarketState,
  type OverviewOpportunity,
  type OverviewPortfolio,
  type OverviewResponse,
  type OverviewRiskEvent,
} from "../lib/api";
import { cn } from "../lib/utils";

const SESSION_LABELS: Record<OverviewMarketState["session"], string> = {
  pre: "盘前",
  regular: "交易中",
  post: "盘后",
  closed: "休市",
};

const SOURCE_LABELS: Record<string, string> = {
  okx: "OKX 行情",
  okx_spot: "OKX 现货行情",
  okx_swap: "OKX 永续行情",
  us_equity_proxy: "美股代理行情",
};

const MODE_LABELS: Record<OverviewOpportunity["mode"], string> = {
  target: "目标驱动",
  market: "市场驱动",
};

const STATUS_LABELS: Record<OverviewOpportunity["status"], string> = {
  new: "新发现",
  reviewed: "已复核",
  adopted: "已采纳",
  rejected: "已拒绝",
  expired: "已过期",
};

const EMPTY_VALUE = "—";

function category(instType: OverviewMarketState["inst_type"]): string {
  return instType === "SWAP" ? "PERP 永续" : "SPOT 现货";
}

function moment(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (value: number) => String(value).padStart(2, "0");
  return (
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ` +
    `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`
  );
}

/** 告警行同时要放规则名与处置状态，日期只留月日；完整时间放在悬停提示里。 */
function shortMoment(iso: string): string {
  return moment(iso).replace(/^\d{4}-/, "");
}

/** 共振强度是 [0,1] 的比率，页面只做百分比换算，数值仍来自后端。 */
function percent(value: string | null): string {
  if (value === null) return EMPTY_VALUE;
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return `${(number * 100).toFixed(0)}%`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border px-2.5 py-1">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate font-mono text-base tabular-nums" title={value}>
        {value}
      </dd>
    </div>
  );
}

function Empty({ children }: { children: string }) {
  return <p className="py-4 text-center text-sm text-muted-foreground">{children}</p>;
}

/** 五个区块共用的紧凑卡片：一屏内要放下两行卡片，边距按 4 而非默认的 6。 */
function Panel({
  title,
  description,
  className,
  children,
}: {
  title: string;
  description: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Card className={className}>
      <CardHeader className="px-4 pb-1.5 pt-3">
        <CardTitle>{title}</CardTitle>
        <CardDescription className="text-xs leading-5">{description}</CardDescription>
      </CardHeader>
      <CardContent className="px-4 pb-3 pt-0">{children}</CardContent>
    </Card>
  );
}

function MarketStateCard({ states }: { states: OverviewMarketState[] }) {
  return (
    <Panel title="市场状态" description="按类别显示资产时段与参考行情来源。">
      {states.length === 0 ? (
        <Empty>暂无市场状态</Empty>
      ) : (
        <ul className="grid gap-2">
          {states.map((state) => (
            <li key={state.inst_type} className="rounded-md border px-2.5 py-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{category(state.inst_type)}</span>
                <span className="rounded-full border px-2 py-0.5 text-xs">
                  {SESSION_LABELS[state.session]}
                </span>
              </div>
              <p className="text-xs leading-5 text-muted-foreground">
                {SOURCE_LABELS[state.primary_source] ?? state.primary_source}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function ResonanceRow({ snapshot }: { snapshot: OverviewMarketSnapshot }) {
  const { breadth, resonance } = snapshot;
  return (
    <li className="rounded-md border px-2.5 py-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">{category(snapshot.inst_type)}</span>
        <span className="font-mono text-base tabular-nums">{percent(resonance.strength)}</span>
      </div>
      <p className="text-xs leading-5 text-muted-foreground">
        {breadth.advancers} 涨 / {breadth.decliners} 跌 / {breadth.unchanged} 平 · 参与{" "}
        {breadth.participants} 个 · 窗口 {resonance.window} 根
      </p>
    </li>
  );
}

function ResonanceCard({ snapshots }: { snapshots: OverviewMarketSnapshot[] }) {
  return (
    <Panel title="共振强度" description="同一类别内部的同向程度。">
      {snapshots.length === 0 ? (
        <Empty>暂无共振数据</Empty>
      ) : (
        <ul className="grid gap-2">
          {snapshots.map((snapshot) => (
            <ResonanceRow key={snapshot.inst_type} snapshot={snapshot} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function PortfolioCard({ portfolio }: { portfolio: OverviewPortfolio }) {
  return (
    <Panel title="组合概览" description="全局敞口与各策略当前持仓数。">
      <dl className="grid grid-cols-3 gap-2">
        <Stat label="净敞口" value={portfolio.net_exposure} />
        <Stat label="总敞口" value={portfolio.gross_exposure} />
        <Stat label="持仓数" value={String(portfolio.open_positions)} />
      </dl>
      {portfolio.strategies.length === 0 ? (
        <Empty>暂无策略组合</Empty>
      ) : (
        <ul className="mt-2 grid max-h-20 gap-1 overflow-y-auto text-sm">
          {portfolio.strategies.map((strategy) => (
            <li
              key={strategy.instance_id}
              className="flex min-w-0 items-center justify-between gap-3 border-t pt-1 first:border-t-0 first:pt-0"
            >
              <span className="min-w-0 truncate">{strategy.name}</span>
              <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                {strategy.open_positions} 个持仓
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function OpportunityCard({ opportunities }: { opportunities: OverviewOpportunity[] }) {
  const points = [...opportunities]
    .reverse()
    .map((item) => ({ time: item.as_of, price: item.score }));

  return (
    <Panel
      title="机会流"
      description="最近判定的机会；折线是这些机会的分数走势。"
      className="xl:col-span-2"
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        {opportunities.length === 0 ? (
          <div className="lg:col-span-2">
            <Empty>暂无机会</Empty>
          </div>
        ) : (
          <>
            <ul className="flex flex-col gap-1.5">
              {opportunities.map((item) => (
                <li
                  key={item.opportunity_id}
                  className="min-w-0 rounded-md border px-2.5 py-1 text-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-medium">
                      {item.anchor_product_key ?? MODE_LABELS[item.mode]}
                    </span>
                    <span className="shrink-0 font-mono text-xs tabular-nums">{item.score}</span>
                  </div>
                  <p className="truncate text-xs leading-4 text-muted-foreground">
                    {MODE_LABELS[item.mode]} · {STATUS_LABELS[item.status]} · {item.legs.length} 条腿 ·{" "}
                    {moment(item.as_of)}
                  </p>
                </li>
              ))}
            </ul>
            <div className="min-w-0">
              <LineChart points={points} label="最近机会分数走势" emptyText="暂无机会分数。" />
            </div>
          </>
        )}
      </div>
    </Panel>
  );
}

function RiskCard({ events }: { events: OverviewRiskEvent[] }) {
  const isResolved = (event: OverviewRiskEvent) => Boolean(event.resolved_at);

  return (
    <Panel title="风险告警" description="未处置的告警排在前面，其余按时间倒序。">
      {events.length === 0 ? (
        <Empty>暂无风险告警</Empty>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {events.map((event) => (
            <li key={event.event_id} className="min-w-0 rounded-md border px-2.5 py-0.5 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate font-mono text-xs" title={event.rule}>
                  {event.rule}
                </span>
                <span
                  className="shrink-0 text-[11px] leading-4 text-muted-foreground"
                  title={moment(event.created_at)}
                >
                  {shortMoment(event.created_at)}
                </span>
                <span
                  className={cn(
                    "shrink-0 rounded-full border px-1.5 text-[11px] leading-4",
                    !isResolved(event)
                      ? "border-rose-600/40 text-rose-600 dark:text-rose-400"
                      : "text-muted-foreground",
                  )}
                >
                  {isResolved(event) ? "已处置" : "未处置"}
                </span>
              </div>
              <p
                className="line-clamp-2 text-xs leading-4 text-muted-foreground"
                title={event.detail}
              >
                {event.detail}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/** 纯展示组件：测试直接渲染它，不依赖网络与浏览器。 */
export function OverviewView({ data }: { data: OverviewResponse }) {
  return (
    <div className="grid gap-3 xl:grid-cols-3">
      <MarketStateCard states={data.market_states} />
      <ResonanceCard snapshots={data.market} />
      <PortfolioCard portfolio={data.portfolio} />
      <OpportunityCard opportunities={data.recent_opportunities} />
      <RiskCard events={data.risk_events} />
    </div>
  );
}

export default function OverviewPage() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchOverview()
      .then((value) => {
        if (active) setOverview(value);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "概览数据加载失败");
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <>
      <PageHeading
        eyebrow="Overview"
        title="概览"
        description="市场驾驶舱：市场状态、共振强度、组合概览、机会流与风险告警。所有数值由后端聚合，页面只读。"
      />

      {error ? (
        <Card className="mb-6 border-rose-600/40">
          <CardContent className="pt-6 text-sm text-rose-600 dark:text-rose-400">{error}</CardContent>
        </Card>
      ) : null}

      {overview === null ? (
        <Card>
          <CardContent className="pt-6 text-sm text-muted-foreground">
            {error ? "无法读取概览数据。" : "正在读取概览数据…"}
          </CardContent>
        </Card>
      ) : (
        <OverviewView data={overview} />
      )}
    </>
  );
}
