import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PageHeading } from "../../components/layout/page-parts";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import {
  fetchWatchlist,
  type WatchlistItem,
  type WatchlistResponse,
  type WatchlistStrategy,
} from "../../lib/api";
import { instTypeLabel, signalTone, signedTone, signedValue } from "../../lib/display";
import { cn } from "../../lib/utils";

type Group = { name: string; items: WatchlistItem[] };

const STATUS_LABELS: Record<WatchlistStrategy["status"], string> = {
  opportunity_discovery: "机会发现",
  strategy_generation: "草稿",
  pending_review: "待审核",
  backtested: "已回测",
  validated: "已验证",
  paper_trading: "模拟交易",
  live_authorized: "已授权",
  live_running: "实盘运行",
  rejected: "已驳回",
};

const MODE_LABELS: Record<WatchlistStrategy["execution_mode"], string> = {
  manual: "人工",
  paper: "模拟",
  live: "实盘",
};

/** 按接口返回的分组顺序分组；接口未列出的分组追加在后，避免静默丢行。 */
function groupItems(response: WatchlistResponse): Group[] {
  const names = [...response.groups];
  for (const item of response.items) {
    if (!names.includes(item.group)) names.push(item.group);
  }
  return names
    .map((name) => ({ name, items: response.items.filter((item) => item.group === name) }))
    .filter((group) => group.items.length > 0);
}

export default function WatchlistPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<WatchlistResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchWatchlist()
      .then((value) => {
        if (active) setData(value);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "自选列表加载失败");
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <>
      <PageHeading
        eyebrow="Watchlist"
        title="自选"
        description="按分组展示关注标的的行情、当前运行策略与最近信号；点击任意一行进入标的详情。"
      />

      {error ? (
        <p className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {!error && !data ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : null}

      {data && data.items.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>暂无自选标的</CardTitle>
          </CardHeader>
        </Card>
      ) : null}

      {data ? (
        <div className="grid gap-6">
          {groupItems(data).map((group) => (
            <Card key={group.name}>
              <CardHeader>
                <div className="flex items-baseline justify-between gap-4">
                  <CardTitle>{group.name}</CardTitle>
                  <span className="text-xs text-muted-foreground">{group.items.length} 个标的</span>
                </div>
              </CardHeader>
              <CardContent>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-xs text-muted-foreground">
                      <th className="py-2 text-left font-medium">标的</th>
                      <th className="py-2 text-left font-medium">形态</th>
                      <th className="py-2 text-left font-medium">策略</th>
                      <th className="py-2 text-right font-medium">最新价</th>
                      <th className="py-2 text-right font-medium">24h 涨跌</th>
                      <th className="py-2 text-right font-medium">24h 成交额</th>
                      <th className="py-2 pl-6 text-left font-medium">信号</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.items.map((item) => {
                      const { instrument, strategy, last_signal } = item;
                      return (
                        <tr
                          key={instrument.inst_id}
                          onClick={() => navigate(`/watchlist/${instrument.inst_id}`)}
                          className="cursor-pointer border-b transition-colors last:border-0 hover:bg-accent/50"
                        >
                          <td className="py-3">
                            <Link
                              to={`/watchlist/${instrument.inst_id}`}
                              onClick={(event) => event.stopPropagation()}
                              className="font-medium underline-offset-4 hover:underline"
                            >
                              {instrument.product_key}
                            </Link>
                            <span className="block font-mono text-xs text-muted-foreground">
                              {instrument.inst_id}
                            </span>
                          </td>
                          <td className="py-3">
                            <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                              {instTypeLabel(instrument.inst_type)}
                            </span>
                          </td>
                          <td className="py-3">
                            {strategy ? (
                              <span className="flex flex-col gap-1">
                                <span className="font-medium">{strategy.name}</span>
                                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                                  <span className="rounded-full border px-2 py-0.5">
                                    {STATUS_LABELS[strategy.status]}
                                  </span>
                                  <span>{MODE_LABELS[strategy.execution_mode]}</span>
                                </span>
                              </span>
                            ) : (
                              <span className="text-muted-foreground">暂无</span>
                            )}
                          </td>
                          <td className="py-3 text-right font-mono">{item.last_price}</td>
                          <td
                            className={cn(
                              "py-3 text-right font-mono",
                              signedTone(item.change_pct_24h),
                            )}
                          >
                            {signedValue(item.change_pct_24h)}%
                          </td>
                          <td className="py-3 text-right font-mono text-muted-foreground">
                            {item.volume_24h_quote}
                          </td>
                          <td className="py-3 pl-6">
                            {last_signal ? (
                              <span className="flex flex-wrap items-center gap-2">
                                <span
                                  className={cn(
                                    "rounded-full border px-2 py-0.5 text-xs font-medium",
                                    signalTone(last_signal.action),
                                  )}
                                >
                                  {last_signal.action}
                                </span>
                                <span className="font-mono text-xs text-muted-foreground">
                                  {last_signal.bar}
                                </span>
                                <span className="text-xs text-muted-foreground">
                                  {last_signal.reason}
                                </span>
                              </span>
                            ) : (
                              <span className="text-muted-foreground">暂无</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}
    </>
  );
}
