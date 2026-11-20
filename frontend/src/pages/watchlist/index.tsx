import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { PageHeading } from "../../components/layout/page-parts";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { StreamNotice, StreamTag } from "../../components/ui/stream-status";
import {
  addWatchlistItem,
  fetchAlerts,
  fetchCandles,
  fetchMarketBreadth,
  fetchWatchlist,
  okxCandleSource,
  removeWatchlistItem,
  updateWatchlistItem,
  type AlertItem,
  type InstrumentRef,
  type MarketBreadthResponse,
  type WatchlistItem,
  type WatchlistResponse,
} from "../../lib/api";
import { instTypeLabel } from "../../lib/display";
import { useQuoteStream } from "../../lib/stream-hooks";
import {
  assetTypeLabel,
  matchesCategory,
  ratioPercent,
  shortUtc,
  WATCHLIST_CATEGORIES,
  type WatchlistCategory,
} from "../../lib/watchlist";
import { aggregateWatchlist, buildPendingDigest } from "../../lib/watchlist-summary";
import { cn } from "../../lib/utils";
import { searchWatchlist } from "../../lib/watchlist-search";
import { WatchlistList } from "./list";
import { WatchlistSummary } from "./summary";

const DEFAULT_GROUP = "默认";
/** 加入自选后只做有限次重读，等后台同步把价格、涨跌和指标写回。 */
const ADD_REFRESH_DELAYS = [2000, 6000, 12000];
const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";
/** 数据未加载时用同一个空数组，避免每次渲染都换引用把下游 effect 打成死循环。 */
const EMPTY_ITEMS: readonly WatchlistItem[] = [];
/** 移动端同一时间只显示一块：汇总还是关注列表。 */
type MobileView = "summary" | "list";

function messageOf(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function CategoryFilter({
  value,
  counts,
  onChange,
}: {
  value: WatchlistCategory;
  counts: Record<WatchlistCategory, number>;
  onChange: (value: WatchlistCategory) => void;
}) {
  return (
    <div role="group" aria-label="分类筛选" className="flex flex-wrap items-center gap-1">
      {WATCHLIST_CATEGORIES.map((item) => (
        <Button
          key={item.value}
          type="button"
          size="sm"
          variant={value === item.value ? "default" : "ghost"}
          aria-pressed={value === item.value}
          onClick={() => onChange(item.value)}
          className="h-7 px-2 text-[11px]"
        >
          {item.label} {counts[item.value]}
        </Button>
      ))}
    </div>
  );
}

function MarketRegimeCard({
  market,
  error,
}: {
  market: MarketBreadthResponse[] | null;
  error: string | null;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>市场环境</CardTitle>
        <CardDescription>
          来自市场总览接口的真实字段；后端没有提供的项目写“未生成”，不在前端推算。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        {!error && market === null ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : null}

        {market === null ? null : (
          <>
            <dl className="grid gap-3 sm:grid-cols-3">
              {[
                ["风险偏好", "后端暂无该字段"],
                ["趋势广度", "后端暂无该字段"],
                ["波动状态", "后端暂无该字段"],
              ].map(([label, note]) => (
                <div key={label} className="rounded-md border px-3 py-2">
                  <dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className="mt-1 text-sm font-medium">未生成</dd>
                  <p className="mt-1 text-xs text-muted-foreground">{note}</p>
                </div>
              ))}
            </dl>

            <div className="mt-4 grid gap-2">
              {market.map((snapshot) => (
                <div key={snapshot.inst_type} className="rounded-md border px-3 py-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-sm font-medium">
                      {instTypeLabel(snapshot.inst_type)}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      截至 {shortUtc(snapshot.as_of)}
                    </span>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    上涨 {snapshot.breadth.advancers} / 下跌 {snapshot.breadth.decliners} / 平{" "}
                    {snapshot.breadth.unchanged} · 参与 {snapshot.breadth.participants} 个 ·
                    共振强度 {ratioPercent(snapshot.resonance.strength)} · 窗口{" "}
                    {snapshot.resonance.window} 根
                  </p>
                </div>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function SearchResults({
  results,
  category,
  tracked,
  busy,
  onAdd,
}: {
  results: InstrumentRef[] | null;
  category: WatchlistCategory;
  tracked: Set<string>;
  busy: string | null;
  onAdd: (instId: string) => void;
}) {
  if (results === null) return null;

  const visible = results.filter((instrument) => matchesCategory(instrument, category));
  if (visible.length === 0) {
    return <p className="mt-4 text-sm text-muted-foreground">没有匹配标的</p>;
  }

  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="py-2 pr-3 text-left font-medium">标的</th>
            <th className="hidden px-2 py-2 text-left font-medium sm:table-cell">名称</th>
            <th className="hidden px-2 py-2 text-left font-medium sm:table-cell">形态</th>
            <th className="px-2 py-2 text-left font-medium">自选</th>
            <th className="py-2 pl-1 text-right font-medium sm:pl-2">
              <span className="sr-only sm:hidden">操作</span>
              <span className="hidden sm:inline">操作</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {visible.map((instrument) => {
            const alreadyTracked = tracked.has(instrument.inst_id);
            return (
              <tr key={instrument.inst_id} className="border-b last:border-0">
                <td className="py-3 pr-3">
                  <Link
                    to={`/watchlist/${instrument.inst_id}`}
                    className="font-mono text-sm underline-offset-4 hover:underline"
                  >
                    {instrument.inst_id}
                  </Link>
                </td>
                <td className="hidden px-2 py-3 sm:table-cell">
                  <span className="font-medium">{instrument.product_key}</span>
                  <span className="block text-xs text-muted-foreground">
                    {assetTypeLabel(instrument.asset_type)}
                  </span>
                </td>
                <td className="hidden px-2 py-3 sm:table-cell">
                  <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                    {instTypeLabel(instrument.inst_type)}
                  </span>
                </td>
                <td className="px-2 py-3 text-xs text-muted-foreground">
                  {alreadyTracked ? "已在自选" : "未加入"}
                </td>
                <td className="py-3 pl-2 text-right">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={alreadyTracked || busy === instrument.inst_id}
                    onClick={() => onAdd(instrument.inst_id)}
                  >
                    {alreadyTracked
                      ? "已加入"
                      : busy === instrument.inst_id
                        ? "加入中…"
                        : "加入自选"}
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function WatchlistPage() {
  const [data, setData] = useState<WatchlistResponse | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  /** 换组失败时递增，让行内分组输入框回到接口返回的值。 */
  const [groupResetToken, setGroupResetToken] = useState(0);

  const [category, setCategory] = useState<WatchlistCategory>("all");
  const [query, setQuery] = useState("");
  /** 加入自选时写进 `POST /api/watchlist` 的分组；留空回落到默认分组。 */
  const [targetGroup, setTargetGroup] = useState(DEFAULT_GROUP);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [results, setResults] = useState<InstrumentRef[] | null>(null);

  const [market, setMarket] = useState<MarketBreadthResponse[] | null>(null);
  const [marketError, setMarketError] = useState<string | null>(null);

  const [pendingAlerts, setPendingAlerts] = useState<readonly AlertItem[]>([]);
  const [alertsError, setAlertsError] = useState<string | null>(null);
  /** 每个标的最近 24 根 1 小时收盘；取不到就是空数组，图里画灰虚线。 */
  const [closes, setCloses] = useState<Record<string, number[]>>({});
  const [view, setView] = useState<MobileView>("summary");

  const searchInputRef = useRef<HTMLInputElement>(null);
  const refreshTimers = useRef<number[]>([]);

  useEffect(() => {
    return () => {
      refreshTimers.current.forEach((timer) => window.clearTimeout(timer));
    };
  }, []);

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

  useEffect(() => {
    let active = true;
    Promise.all([fetchMarketBreadth("SPOT"), fetchMarketBreadth("SWAP")])
      .then((value) => {
        if (active) setMarket(value);
      })
      .catch((reason: unknown) => {
        if (active) setMarketError(messageOf(reason, "市场环境加载失败"));
      });
    return () => {
      active = false;
    };
  }, []);

  /** 「需要处理」里的待处理提醒；拿不到时如实说明，不把条数当成 0。 */
  useEffect(() => {
    let active = true;
    fetchAlerts({ status: "pending" })
      .then((value) => {
        if (!active) return;
        setPendingAlerts(value.items);
        setAlertsError(null);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setPendingAlerts([]);
        setAlertsError(messageOf(reason, "待处理提醒加载失败"));
      });
    return () => {
      active = false;
    };
  }, [reloadToken]);

  const items = data?.items ?? EMPTY_ITEMS;

  const visibleItems = useMemo(
    () => items.filter((item) => matchesCategory(item.instrument, category)),
    [items, category],
  );

  /** 分类筛选是联动的：列表与三块汇总都按当前分类的标的统计；切回「全部」恢复全量。 */
  const aggregate = useMemo(() => aggregateWatchlist(visibleItems), [visibleItems]);
  const pending = useMemo(
    () => buildPendingDigest(visibleItems, pendingAlerts),
    [visibleItems, pendingAlerts],
  );

  const categoryCounts = useMemo(() => {
    const counts = { all: 0, stock_swap: 0, crypto: 0 } as Record<WatchlistCategory, number>;
    for (const entry of WATCHLIST_CATEGORIES) {
      counts[entry.value] = items.filter((item) =>
        matchesCategory(item.instrument, entry.value),
      ).length;
    }
    return counts;
  }, [items]);

  /** 分时线取最近 24 根 1 小时收盘；`instIds` 用可见集合，筛选后不重复请求。 */
  useEffect(() => {
    let active = true;

    if (visibleItems.length === 0) {
      setCloses({});
      return () => {
        active = false;
      };
    }

    void Promise.all(
      visibleItems.map(async (item) => {
        try {
          const series = await fetchCandles(
            item.instrument.inst_id,
            "1h",
            okxCandleSource(item.instrument.inst_type),
            24,
          );
          return [
            item.instrument.inst_id,
            series.candles.map((candle) => Number(candle.close)),
          ] as const;
        } catch {
          // 分时线取不到不是错误：图里画灰虚线，不用假数据顶上。
          return [item.instrument.inst_id, [] as number[]] as const;
        }
      }),
    ).then((entries) => {
      if (active) setCloses(Object.fromEntries(entries));
    });

    return () => {
      active = false;
    };
  }, [visibleItems]);

  const { quotes, liveness } = useQuoteStream(items.map((item) => item.instrument.inst_id));
  const tracked = new Set(items.map((item) => item.instrument.inst_id));
  /** 行内分组输入框的可选项：接口返回的分组名加默认分组，允许直接输入新名字。 */
  const groupNames = useMemo(
    () => [...new Set([DEFAULT_GROUP, ...(data?.groups ?? [])])],
    [data],
  );

  function reload(): void {
    setError(null);
    setReloadToken((token) => token + 1);
  }

  function focusSearch(): void {
    searchInputRef.current?.focus();
    searchInputRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
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
      setResults(await searchWatchlist(keyword));
    } catch (reason: unknown) {
      setResults(null);
      setSearchError(messageOf(reason, "搜索失败"));
    } finally {
      setSearching(false);
    }
  }

  function scheduleAddRefreshes(): void {
    refreshTimers.current.forEach((timer) => window.clearTimeout(timer));
    refreshTimers.current = ADD_REFRESH_DELAYS.map((delay) =>
      window.setTimeout(() => setReloadToken((token) => token + 1), delay),
    );
  }

  async function handleAdd(instId: string): Promise<void> {
    setBusy(instId);
    setActionError(null);
    try {
      await addWatchlistItem(instId, targetGroup.trim() || DEFAULT_GROUP);
      reload();
      scheduleAddRefreshes();
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

  /** 行内分组切换：写回 `PATCH /api/watchlist/{inst_id}`，失败时让输入框回到接口的值。 */
  async function handleMove(instId: string, group: string): Promise<void> {
    setBusy(instId);
    setActionError(null);
    try {
      await updateWatchlistItem(instId, group);
      reload();
    } catch (reason: unknown) {
      setActionError(messageOf(reason, "切换分组失败"));
      setGroupResetToken((token) => token + 1);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeading
        eyebrow="Watchlist"
        title="自选"
        description="左边是关注的全部标的，右边是这些标的的汇总；单个标的的细节在详情页。"
      />

      <datalist id="watchlist-groups">
        {groupNames.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>

      <Card className="mb-6">
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle>搜索标的</CardTitle>
              <CardDescription>
                按代码或产品键搜索已同步的标的；分类筛选作用于搜索结果、关注列表与关注汇总。
              </CardDescription>
            </div>
            <CategoryFilter value={category} counts={categoryCounts} onChange={setCategory} />
          </div>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={(event) => void handleSearch(event)}
            className="flex flex-col gap-2 sm:flex-row"
          >
            <input
              ref={searchInputRef}
              aria-label="搜索关键字"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="例如 AAPL、比特币、BTC"
              className={cn(INPUT_CLASS, "sm:max-w-md")}
            />
            <Button type="submit" disabled={searching} className="sm:w-auto">
              {searching ? "搜索中…" : "搜索"}
            </Button>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              加入分组
              <input
                list="watchlist-groups"
                aria-label="加入自选的分组"
                value={targetGroup}
                onChange={(event) => setTargetGroup(event.target.value)}
                placeholder={DEFAULT_GROUP}
                className={cn(INPUT_CLASS, "h-9 w-32 px-2")}
              />
            </label>
          </form>

          {searchError ? (
            <p className="mt-3 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
              {searchError}
            </p>
          ) : null}

          <SearchResults
            results={results}
            category={category}
            tracked={tracked}
            busy={busy}
            onAdd={(instId) => void handleAdd(instId)}
          />
        </CardContent>
      </Card>

      {error ? (
        <p className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {alertsError ? (
        <p className="mb-4 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {alertsError}
        </p>
      ) : null}

      {actionError ? (
        <p className="mb-4 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {actionError}
        </p>
      ) : null}

      {!error && !data ? <p className="text-sm text-muted-foreground">加载中…</p> : null}

      {data && items.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>还没有自选标的</CardTitle>
            <CardDescription>
              在上方搜索框输入代码或产品键，把第一只标的加入自选。加入后行情与指标会按日线补齐。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button type="button" onClick={focusSearch}>
              加入第一只标的
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {data && items.length > 0 ? (
        <>
          <div className="wl-tabs" role="tablist" aria-label="切换视图">
            <button
              type="button"
              role="tab"
              aria-selected={view === "summary"}
              onClick={() => setView("summary")}
            >
              汇总
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === "list"}
              onClick={() => setView("list")}
            >
              关注列表
            </button>
          </div>

          <div className="wl-grid" data-view={view}>
            <section className="wl-list rounded-lg border bg-card text-card-foreground shadow-sm">
              <header className="flex flex-wrap items-baseline justify-between gap-2 border-b px-4 py-3">
                <div>
                  <h2 className="text-sm font-semibold tracking-tight">关注列表</h2>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    价格按推送更新；日涨跌、趋势、RSI(14)、ATR(14)%、K 线覆盖与最近更新时间来自
                    HTTP 快照，快照时间见每行「最近更新时间」。
                  </p>
                </div>
                <span className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <StreamTag liveness={liveness} />
                  {visibleItems.length} 个
                </span>
              </header>

              <div className="flex flex-wrap items-center gap-1 border-b px-3 py-2">
                <CategoryFilter value={category} counts={categoryCounts} onChange={setCategory} />
              </div>

              {liveness === "live" ? null : (
                <div className="px-3 pt-2">
                  <StreamNotice liveness={liveness} subject="价格" />
                </div>
              )}

              {visibleItems.length === 0 ? (
                <p className="px-4 py-6 text-center text-sm text-muted-foreground">
                  当前分类下没有标的。
                  <Button
                    type="button"
                    variant="link"
                    className="h-auto px-2 py-0"
                    onClick={() => setCategory("all")}
                  >
                    查看全部
                  </Button>
                </p>
              ) : (
                <WatchlistList
                  items={visibleItems}
                  quotes={quotes}
                  closes={closes}
                  busy={busy}
                  groupResetToken={groupResetToken}
                  onRemove={(instId) => void handleRemove(instId)}
                  onMove={(instId, group) => void handleMove(instId, group)}
                />
              )}
            </section>

            <WatchlistSummary aggregate={aggregate} pending={pending} />
          </div>
        </>
      ) : null}

      <div className="mt-6">
        <MarketRegimeCard market={market} error={marketError} />
      </div>
    </>
  );
}
