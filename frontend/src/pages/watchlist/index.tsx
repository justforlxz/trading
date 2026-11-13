import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PageHeading } from "../../components/layout/page-parts";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  addWatchlistItem,
  fetchWatchlist,
  removeWatchlistItem,
  searchInstruments,
  updateWatchlistItem,
  type InstrumentRef,
  type WatchlistItem,
  type WatchlistResponse,
  type WatchlistStrategy,
} from "../../lib/api";
import { instTypeLabel, signalTone, signedTone, signedValue } from "../../lib/display";
import { cn } from "../../lib/utils";

const DEFAULT_GROUP = "默认";
const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

type InstType = InstrumentRef["inst_type"];
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

function messageOf(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

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
  const [reloadToken, setReloadToken] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [groupResetToken, setGroupResetToken] = useState(0);

  const [query, setQuery] = useState("");
  const [instType, setInstType] = useState<InstType | "">("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [results, setResults] = useState<InstrumentRef[] | null>(null);

  useEffect(() => {
    let active = true;
    fetchWatchlist()
      .then((value) => {
        if (active) setData(value);
      })
      .catch((reason: unknown) => {
        if (active) setError(messageOf(reason, "自选列表加载失败"));
      });
    return () => {
      active = false;
    };
  }, [reloadToken]);

  function reload(): void {
    setError(null);
    setReloadToken((token) => token + 1);
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const keyword = query.trim();
    if (keyword === "") {
      setResults(null);
      setSearchError(null);
      return;
    }

    setSearching(true);
    setSearchError(null);
    try {
      const response = await searchInstruments(
        keyword,
        instType === "" ? undefined : instType,
      );
      setResults(response.items);
    } catch (reason: unknown) {
      setResults(null);
      setSearchError(messageOf(reason, "搜索失败"));
    } finally {
      setSearching(false);
    }
  }

  async function handleAdd(instId: string): Promise<void> {
    setBusy(instId);
    setActionError(null);
    try {
      await addWatchlistItem(instId, DEFAULT_GROUP);
      reload();
    } catch (reason: unknown) {
      setActionError(messageOf(reason, "加入自选失败"));
    } finally {
      setBusy(null);
    }
  }

  async function handleRemove(instId: string): Promise<void> {
    setBusy(instId);
    setActionError(null);
    try {
      await removeWatchlistItem(instId);
      reload();
    } catch (reason: unknown) {
      setActionError(messageOf(reason, "移出自选失败"));
    } finally {
      setBusy(null);
    }
  }

  async function handleMove(instId: string, group: string): Promise<void> {
    setBusy(instId);
    setActionError(null);
    try {
      await updateWatchlistItem(instId, group);
      reload();
    } catch (reason: unknown) {
      setActionError(messageOf(reason, "切换分组失败"));
      // 分组没有保存成功时让输入框重新挂载，恢复成列表里的实际分组。
      setGroupResetToken((token) => token + 1);
    } finally {
      setBusy(null);
    }
  }

  const tracked = new Set(data?.items.map((item) => item.instrument.inst_id) ?? []);
  const groupNames = [...new Set([DEFAULT_GROUP, ...(data?.groups ?? [])])];

  return (
    <>
      <PageHeading
        eyebrow="Watchlist"
        title="自选"
        description="搜索已同步的标的加入自选，按分组查看行情、当前运行策略与最近信号；点击任意一行进入标的详情。"
      />

      <datalist id="watchlist-groups">
        {groupNames.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>搜索标的</CardTitle>
          <CardDescription>
            按代码或产品键搜索已同步的标的；加入自选后可直接进入详情。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={(event) => void handleSearch(event)} className="flex flex-wrap items-center gap-2">
            <input
              aria-label="搜索关键字"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="例如 AAPL"
              className={cn(INPUT_CLASS, "max-w-xs")}
            />
            <select
              aria-label="形态"
              value={instType}
              onChange={(event) => {
                setInstType(event.target.value as InstType | "");
                setResults(null);
                setSearchError(null);
              }}
              className={cn(INPUT_CLASS, "w-auto")}
            >
              <option value="">全部形态</option>
              <option value="SPOT">现货（SPOT）</option>
              <option value="SWAP">永续（SWAP）</option>
            </select>
            <Button type="submit" disabled={searching}>
              {searching ? "搜索中…" : "搜索"}
            </Button>
          </form>

          {searchError ? (
            <p className="mt-3 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
              {searchError}
            </p>
          ) : null}

          {results === null ? null : results.length === 0 ? (
            <p className="mt-4 text-sm text-muted-foreground">没有匹配标的</p>
          ) : (
            <table className="mt-4 w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="py-2 text-left font-medium">标的</th>
                  <th className="py-2 text-left font-medium">产品</th>
                  <th className="py-2 text-left font-medium">形态</th>
                  <th className="py-2 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {results.map((instrument) => {
                  const alreadyTracked = tracked.has(instrument.inst_id);
                  return (
                    <tr key={instrument.inst_id} className="border-b last:border-0">
                      <td className="py-3">
                        <Link
                          to={`/watchlist/${instrument.inst_id}`}
                          className="font-mono text-sm underline-offset-4 hover:underline"
                        >
                          {instrument.inst_id}
                        </Link>
                      </td>
                      <td className="py-3">{instrument.product_key}</td>
                      <td className="py-3">
                        <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                          {instTypeLabel(instrument.inst_type)}
                        </span>
                      </td>
                      <td className="py-3">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={alreadyTracked || busy === instrument.inst_id}
                            onClick={() => void handleAdd(instrument.inst_id)}
                          >
                            {alreadyTracked ? "已加入" : busy === instrument.inst_id ? "加入中…" : "加入自选"}
                          </Button>
                          <Link
                            to={`/watchlist/${instrument.inst_id}`}
                            className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                          >
                            详情
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {error ? (
        <p className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {actionError ? (
        <p className="mb-4 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {actionError}
        </p>
      ) : null}

      {!error && !data ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : null}

      {data && data.items.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>暂无自选标的</CardTitle>
            <CardDescription>在上方搜索框输入代码或产品键，把标的加入自选。</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      {data ? (
        <div className="grid min-w-0 gap-6">
          {groupItems(data).map((group) => (
            <Card key={group.name} className="min-w-0">
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
                      <th className="py-2 text-left font-medium">分组</th>
                      <th className="py-2 text-left font-medium">策略</th>
                      <th className="py-2 text-right font-medium">最新价</th>
                      <th className="py-2 text-right font-medium">24h 涨跌</th>
                      <th className="py-2 text-right font-medium">24h 成交额</th>
                      <th className="py-2 pl-6 text-left font-medium">信号</th>
                      <th className="py-2 pl-6 text-right font-medium">操作</th>
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
                            <input
                              key={`${instrument.inst_id}:${item.group}:${groupResetToken}`}
                              list="watchlist-groups"
                              defaultValue={item.group}
                              aria-label={`${instrument.inst_id} 的分组`}
                              disabled={busy === instrument.inst_id}
                              onClick={(event) => event.stopPropagation()}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                  event.preventDefault();
                                  event.currentTarget.blur();
                                }
                              }}
                              onBlur={(event) => {
                                const next = event.currentTarget.value.trim() || DEFAULT_GROUP;
                                if (next !== item.group) void handleMove(instrument.inst_id, next);
                              }}
                              className={cn(INPUT_CLASS, "h-8 w-28 px-2 text-xs")}
                            />
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
                          <td className="py-3 pl-6 text-right">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              aria-label={`移出 ${instrument.inst_id}`}
                              disabled={busy === instrument.inst_id}
                              onClick={(event) => {
                                event.stopPropagation();
                                void handleRemove(instrument.inst_id);
                              }}
                            >
                              {busy === instrument.inst_id ? "处理中…" : "移出"}
                            </Button>
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
