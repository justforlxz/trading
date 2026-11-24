import { MoreHorizontal, Trash2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import type { WatchlistItem } from "../../lib/api";
import { signedTone, signedValue } from "../../lib/display";
import type { QuoteUpdate } from "../../lib/stream";
import { cn } from "../../lib/utils";
import { metricText } from "../../lib/watchlist";
import { signalText, signalTone, TONE_BAR_COLORS, toneClass } from "../../lib/watchlist-summary";
import { Sparkline } from "./sparkline";
/** 首次加载时先摆出的占位行数量；6 行与常见屏幕高度下的首屏一致。 */
const SKELETON_ROWS = 6;

/** 四列宽度只在这里声明一次，骨架表格与真实表格共用，几何不会分叉。 */
const WATCHLIST_COLUMNS = (
  <colgroup>
    <col className="wl-col-target" />
    <col className="wl-col-24h" />
    <col className="wl-col-price" />
    <col className="wl-col-signal" />
  </colgroup>
);

/** 表头也只在这里声明一次：占位期间与数据到达后是同一份节点，列宽与行高不会跳动。 */
const WATCHLIST_HEAD = (
  <thead>
    <tr className="border-b">
      <th className="wl-cell-first py-2 pr-2 text-left text-[11px] font-medium text-muted-foreground">
        标的
      </th>
      <th className="wl-col-24h px-3 py-2 text-left text-[11px] font-medium text-muted-foreground">
        24H
      </th>
      <th className="px-3 py-2 text-right text-[11px] font-medium text-muted-foreground">
        价格 / 涨跌
      </th>
      <th className="wl-cell-last py-2 pl-3 text-right text-[11px] font-medium text-muted-foreground">
        信号
      </th>
    </tr>
  </thead>
);

/**
 * 占位行：与真实行共用 `.wl-row`（51px），四列各自一块呼吸色块，
 * 第一列两块对应标的与产品键两行文字。
 */
const WATCHLIST_SKELETON_ROWS = (
  <tbody aria-hidden="true">
    {Array.from({ length: SKELETON_ROWS }, (_, index) => (
      <tr key={`wl-skeleton-${index}`} className="wl-row border-b last:border-0">
        <td className="wl-cell-first py-2 pr-2 align-middle">
          <span className="block h-3 w-28 animate-pulse rounded bg-muted" />
          <span className="mt-1.5 block h-2.5 w-20 animate-pulse rounded bg-muted" />
        </td>
        <td className="wl-col-24h px-3 py-2 align-middle">
          <span className="block h-3 w-10 animate-pulse rounded bg-muted" />
        </td>
        <td className="px-3 py-2 text-right align-middle">
          <span className="ml-auto block h-3 w-16 animate-pulse rounded bg-muted" />
        </td>
        <td className="wl-cell-last py-2 pl-3 text-right align-middle">
          <span className="ml-auto block h-3 w-12 animate-pulse rounded bg-muted" />
        </td>
      </tr>
    ))}
  </tbody>
);

/**
 * 关注列表：固定 4 列，行高 51px。
 *
 * 列宽与内边距写在 `index.css` 的 `.wl-col-*` / `.wl-table` 里，表头与单元格共用同一组
 * 声明，所以两边的 x 坐标天然一致；24H 列在 ≤900px 由 `.wl-col-24h` 整列隐藏。
 *
 * 分组不在行内常驻输入框里改：行尾的菜单提供「移动到分组」，选中后走 `onMove`。
 */
export function WatchlistList({
  items,
  quotes,
  closes,
  busy,
  groups,
  onRemove,
  onMove,
  state,
  loading = false,
}: {
  items: readonly WatchlistItem[];
  quotes: Readonly<Record<string, QuoteUpdate>>;
  closes: Readonly<Record<string, number[]>>;
  busy: string | null;
  /** 「移动到分组」的可选分组，来自 `GET /api/watchlist` 的 `groups`。 */
  groups: readonly string[];
  onRemove: (instId: string) => void;
  onMove: (instId: string, group: string) => void;
  /** 画占位行还是真实行：由 `watchlistPanelState` 决定，这里不再自己判断。 */
  state: "skeleton" | "rows";
  /** 请求在途：真实行原样保留，只在上面盖一层遮罩。 */
  loading?: boolean;
}) {
  const navigate = useNavigate();

  // 首次加载：表头与占位行立即出现，行高与真实行一致，替换时不产生纵向跳动。
  if (state === "skeleton") {
    return (
      <table className="wl-table text-sm" aria-busy="true" aria-label="关注列表加载中">
        {WATCHLIST_COLUMNS}
        {WATCHLIST_HEAD}
        {WATCHLIST_SKELETON_ROWS}
      </table>
    );
  }

  return (
    <div className="relative">
      <table className="wl-table text-sm" aria-busy={loading || undefined}>
        {WATCHLIST_COLUMNS}
        {WATCHLIST_HEAD}
        <tbody>
          {items.map((item) => {
            const { instrument } = item;
            const instId = instrument.inst_id;
            const live = quotes[instId];
            const tone = signalTone(item);
            const signal = signalText(item);
            const change = item.change_pct_24h;

            return (
              <tr
                key={instId}
                onClick={() => navigate(`/watchlist/${instId}`)}
                className="wl-row cursor-pointer border-b transition-colors last:border-0 hover:bg-accent/50"
              >
                <td
                  className="wl-target-cell wl-cell-first py-2 pr-2 align-middle"
                  style={{ boxShadow: `inset 3px 0 0 ${TONE_BAR_COLORS[tone]}` }}
                >
                  <Link
                    to={`/watchlist/${instId}`}
                    onClick={(event) => event.stopPropagation()}
                    className="block truncate pr-14 text-sm font-semibold no-underline underline-offset-4 hover:underline"
                    style={{ lineHeight: 1.25 }}
                  >
                    {instId}
                  </Link>
                  <span
                    className="block truncate pr-14 text-[11px] text-muted-foreground"
                    style={{ lineHeight: 1.25 }}
                  >
                    {instrument.product_key} · {item.group}
                  </span>
                  <details
                    className="wl-more absolute right-7 top-1/2 -translate-y-1/2"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <summary
                      aria-label={`${instId} 的更多操作`}
                      title="更多操作"
                      className="cursor-pointer rounded p-1 text-muted-foreground transition-colors hover:bg-accent"
                    >
                      <MoreHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
                    </summary>
                    <div
                      role="menu"
                      aria-label={`${instId} 的分组操作`}
                      className="absolute right-0 top-full z-20 mt-1 w-44 rounded-md border bg-card p-1 text-left shadow-md"
                    >
                      <p className="px-2 py-1 text-[11px] text-muted-foreground">移动到分组</p>
                      {groups.map((name) => (
                        <button
                          key={name}
                          type="button"
                          role="menuitem"
                          disabled={busy === instId || name === item.group}
                          onClick={(event) => {
                            event.stopPropagation();
                            event.currentTarget.closest("details")?.removeAttribute("open");
                            onMove(instId, name);
                          }}
                          className={cn(
                            "block w-full rounded px-2 py-1 text-left text-xs transition-colors hover:bg-accent disabled:opacity-50",
                            name === item.group && "font-medium",
                          )}
                        >
                          {name === item.group ? `${name} · 当前` : name}
                        </button>
                      ))}
                    </div>
                  </details>
                  <button
                    type="button"
                    aria-label={`移出 ${instId}`}
                    disabled={busy === instId}
                    onClick={(event) => {
                      event.stopPropagation();
                      onRemove(instId);
                    }}
                    className="wl-remove absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-destructive disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </td>

                <td className="wl-col-24h px-3 py-2 align-middle">
                  <Sparkline closes={closes[instId] ?? []} />
                </td>

                <td className="px-3 py-2 text-right align-middle">
                  <span
                    className="block truncate font-mono text-sm font-semibold tabular-nums"
                    style={{ lineHeight: 1.25 }}
                  >
                    {metricText(live?.last ?? item.last_price, item.data_status)}
                  </span>
                  <span
                    className={cn(
                      "block truncate font-mono text-[11px] tabular-nums",
                      change === null ? "text-muted-foreground" : signedTone(change),
                    )}
                    style={{ lineHeight: 1.25 }}
                  >
                    {change === null ? "—" : `${signedValue(change)}%`}
                  </span>
                </td>

                <td className="wl-cell-last py-2 pl-3 text-right align-middle">
                  <span
                    className={cn("block truncate text-[11px] font-medium", toneClass(tone))}
                    title={signal}
                  >
                    {signal}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {loading ? (
        <div
          aria-hidden="true"
          data-testid="watchlist-refreshing"
          className="absolute inset-0 z-10 bg-background/50"
        />
      ) : null}
    </div>
  );
}
