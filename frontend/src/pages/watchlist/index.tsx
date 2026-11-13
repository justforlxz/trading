import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Trash2 } from "lucide-react";

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
  fetchMarketOverview,
  fetchWatchlist,
  removeWatchlistItem,
  searchInstruments,
  updateWatchlistItem,
  type InstrumentRef,
  type MarketOverviewResponse,
  type WatchlistItem,
  type WatchlistResponse,
} from "../../lib/api";
import { instTypeLabel, signedTone, signedValue } from "../../lib/display";
import {
  assetTypeLabel,
  coverageText,
  dataTimeText,
  matchesCategory,
  metricText,
  ratioPercent,
  shortUtc,
  trendText,
  trendTone,
  WATCHLIST_CATEGORIES,
  type WatchlistCategory,
} from "../../lib/watchlist";
import { cn } from "../../lib/utils";

const DEFAULT_GROUP = "默认";
const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

function messageOf(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function CategoryFilter({
  value,
  onChange,
}: {
  value: WatchlistCategory;
  onChange: (value: WatchlistCategory) => void;
}) {
  return (
    <div
      role="group"
      aria-label="分类筛选"
      className="flex flex-wrap items-center gap-1 rounded-md border p-1"
    >
      {WATCHLIST_CATEGORIES.map((item) => (
        <Button
          key={item.value}
          type="button"
          size="sm"
          variant={value === item.value ? "default" : "ghost"}
          aria-pressed={value === item.value}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </Button>
      ))}
    </div>
  );
}

function MarketRegimeCard({
  market,
  error,
}: {
  market: MarketOverviewResponse[] | null;
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

function WatchlistTable({
  items,
  busy,
  groupResetToken,
  onRemove,
  onMove,
}: {
  items: WatchlistItem[];
  busy: string | null;
  groupResetToken: number;
  onRemove: (instId: string) => void;
  onMove: (instId: string, group: string) => void;
}) {
  const navigate = useNavigate();

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs sm:text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="py-2 pr-2 text-left font-medium">标的</th>
            <th className="px-1.5 py-2 text-right font-medium sm:px-2">最新价</th>
            <th className="px-1.5 py-2 text-right font-medium sm:px-2">日涨跌</th>
            <th className="px-1.5 py-2 text-left font-medium sm:px-2">趋势</th>
            <th className="hidden px-2 py-2 text-right font-medium lg:table-cell">RSI(14)</th>
            <th className="hidden px-2 py-2 text-right font-medium lg:table-cell">ATR(14)</th>
            <th className="hidden px-2 py-2 text-left font-medium md:table-cell">数据</th>
            <th className="py-2 pl-1 text-right font-medium sm:pl-2">
              <span className="sr-only sm:hidden">操作</span>
              <span className="hidden sm:inline">操作</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const { instrument } = item;
            return (
              <tr
                key={instrument.inst_id}
                onClick={() => navigate(`/watchlist/${instrument.inst_id}`)}
                className="cursor-pointer border-b transition-colors last:border-0 hover:bg-accent/50"
              >
                <td className="py-3 pr-2 align-top">
                  <Link
                    to={`/watchlist/${instrument.inst_id}`}
                    onClick={(event) => event.stopPropagation()}
                    className="font-mono font-medium underline-offset-4 hover:underline"
                  >
                    {instrument.inst_id}
                  </Link>
                  <span className="block text-xs text-muted-foreground">
                    {instrument.product_key} · {assetTypeLabel(instrument.asset_type)}
                  </span>
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
                      if (next !== item.group) onMove(instrument.inst_id, next);
                    }}
                    className={cn(INPUT_CLASS, "mt-1 h-7 w-16 px-2 text-xs sm:w-24")}
                  />
                </td>
                <td className="px-1.5 py-3 text-right align-top font-mono tabular-nums sm:px-2">
                  {metricText(item.last_price, item.data_status)}
                </td>
                <td
                  className={cn(
                    "px-1.5 py-3 text-right align-top font-mono tabular-nums sm:px-2",
                    item.change_pct_24h === null ? "" : signedTone(item.change_pct_24h),
                  )}
                >
                  {item.change_pct_24h === null
                    ? metricText(null, item.data_status)
                    : `${signedValue(item.change_pct_24h)}%`}
                </td>
                <td className="px-1.5 py-3 align-top sm:px-2">
                  <span
                    className={cn(
                      "whitespace-nowrap text-xs font-medium",
                      trendTone(item.trend),
                    )}
                  >
                    {trendText(item.trend, item.data_status)}
                  </span>
                </td>
                <td className="hidden px-2 py-3 text-right align-top font-mono tabular-nums lg:table-cell">
                  {metricText(item.rsi_14, item.data_status)}
                </td>
                <td className="hidden px-2 py-3 text-right align-top font-mono tabular-nums lg:table-cell">
                  {item.atr_pct_14 === null
                    ? metricText(null, item.data_status)
                    : `${item.atr_pct_14}%`}
                </td>
                <td className="hidden px-2 py-3 align-top text-xs text-muted-foreground md:table-cell">
                  <span className="block whitespace-nowrap">{coverageText(item)}</span>
                  <span className="block whitespace-nowrap">{dataTimeText(item.last_candle_at)}</span>
                </td>
                <td className="py-3 pl-1 text-right align-top sm:pl-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="px-2 sm:px-3"
                    aria-label={`移出 ${instrument.inst_id}`}
                    disabled={busy === instrument.inst_id}
                    onClick={(event) => {
                      event.stopPropagation();
                      onRemove(instrument.inst_id);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5 sm:hidden" aria-hidden="true" />
                    <span className="hidden sm:inline">
                      {busy === instrument.inst_id ? "处理中…" : "移出"}
                    </span>
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
  const [groupResetToken, setGroupResetToken] = useState(0);

  const [category, setCategory] = useState<WatchlistCategory>("all");
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [results, setResults] = useState<InstrumentRef[] | null>(null);

  const [market, setMarket] = useState<MarketOverviewResponse[] | null>(null);
  const [marketError, setMarketError] = useState<string | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

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
    Promise.all([fetchMarketOverview("SPOT"), fetchMarketOverview("SWAP")])
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
      const response = await searchInstruments(keyword);
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
      setGroupResetToken((token) => token + 1);
    } finally {
      setBusy(null);
    }
  }

  const items = data?.items ?? [];
  const visibleItems = items.filter((item) => matchesCategory(item.instrument, category));
  const tracked = new Set(items.map((item) => item.instrument.inst_id));
  const groupNames = [...new Set([DEFAULT_GROUP, ...(data?.groups ?? [])])];

  return (
    <>
      <PageHeading
        eyebrow="Watchlist"
        title="自选"
        description="搜索标的加入自选；点任意一行进入分析，进入后可以切换标的。列表里的价格、趋势、RSI、ATR 与数据覆盖都来自后端真实数据。"
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
                按代码或产品键搜索已同步的标的；分类筛选同时作用于搜索结果与自选列表。
              </CardDescription>
            </div>
            <CategoryFilter value={category} onChange={setCategory} />
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={(event) => void handleSearch(event)} className="flex flex-col gap-2 sm:flex-row">
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
        <Card className="mb-6">
          <CardHeader>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <CardTitle>自选列表</CardTitle>
                <CardDescription>
                  {visibleItems.length} 个标的 · 日线 · RSI(14) · ATR(14)
                </CardDescription>
              </div>
              <span className="text-xs text-muted-foreground">点击标的进入技术分析</span>
            </div>
          </CardHeader>
          <CardContent className="px-3 pb-3 sm:px-6">
            {visibleItems.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
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
              <WatchlistTable
                items={visibleItems}
                busy={busy}
                groupResetToken={groupResetToken}
                onRemove={(instId) => void handleRemove(instId)}
                onMove={(instId, group) => void handleMove(instId, group)}
              />
            )}
          </CardContent>
        </Card>
      ) : null}

      <MarketRegimeCard market={market} error={marketError} />
    </>
  );
}
