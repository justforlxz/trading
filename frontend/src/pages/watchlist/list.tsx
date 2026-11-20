import { Trash2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import type { WatchlistItem } from "../../lib/api";
import { instTypeLabel, signedTone, signedValue } from "../../lib/display";
import type { QuoteUpdate } from "../../lib/stream";
import { cn } from "../../lib/utils";
import { coverageText, metricText, trendText, trendTone } from "../../lib/watchlist";
import { signalText, signalTone, TONE_BAR_COLORS, toneClass } from "../../lib/watchlist-summary";
import { Sparkline } from "./sparkline";

const DEFAULT_GROUP = "默认";
const GROUP_INPUT_CLASS =
  "mt-1 h-6 w-[76px] rounded border border-input bg-transparent px-1 text-[11px] outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 sm:w-[92px]";

const HEAD_CLASS = "px-1.5 py-2 text-[11px] font-medium text-muted-foreground whitespace-nowrap";

/** 最近更新时间按「日期 / 时分 UTC」拆两行，列宽才塞得下七列指标。 */
function snapshotLines(iso: string | null): [string, string] {
  if (iso === null) return ["尚未同步", ""];
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return ["尚未同步", ""];
  const pad = (part: number) => String(part).padStart(2, "0");
  return [
    `${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`,
    `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`,
  ];
}

/** K 线覆盖按「根数 / 指标待补」拆两行，`coverageText` 的口径不变。 */
function coverageLines(item: WatchlistItem): [string, string] {
  const [main, note] = coverageText(item).split(" · ");
  return [main ?? "", note ?? ""];
}

/**
 * 关注列表：`docs/prd/v6.md` 3.1 的七列指标 + 行内分组切换。
 *
 * 列顺序即 PRD 的「v6 列表指标列」：最新价、日涨跌、趋势、RSI(14)、ATR(14)%、K 线覆盖、
 * 最近更新时间。价格由推送更新，其余字段来自 `GET /api/watchlist` 的 HTTP 快照，
 * 「最近更新时间」列同时标出这份快照的时间，缺数据写「尚未同步 / 未生成」而不补 0。
 *
 * 24H 分时线放在「最新价」单元格里（沿用 MKACG-917 的分时线，不占独立列），
 * 「信号」列沿用同一版式；它们是 PRD 指标列之外的附加信息。九列在 1440px 的
 * 左栏宽度内全部显示，不靠横向滚动。
 */
export function WatchlistList({
  items,
  quotes,
  closes,
  busy,
  groupResetToken,
  onRemove,
  onMove,
}: {
  items: readonly WatchlistItem[];
  quotes: Readonly<Record<string, QuoteUpdate>>;
  closes: Readonly<Record<string, number[]>>;
  busy: string | null;
  groupResetToken: number;
  onRemove: (instId: string) => void;
  onMove: (instId: string, group: string) => void;
}) {
  const navigate = useNavigate();

  return (
    <div className="overflow-x-auto">
      <table className="wl-table text-sm">
        <thead>
          <tr className="border-b">
            <th className={cn(HEAD_CLASS, "wl-cell-first pl-4 text-left")}>标的</th>
            <th className={cn(HEAD_CLASS, "text-right")}>最新价</th>
            <th className={cn(HEAD_CLASS, "text-right")}>日涨跌</th>
            <th className={cn(HEAD_CLASS, "text-left")}>趋势</th>
            <th className={cn(HEAD_CLASS, "text-right")}>RSI(14)</th>
            <th className={cn(HEAD_CLASS, "text-right")}>ATR(14)%</th>
            <th className={cn(HEAD_CLASS, "text-left")}>K 线覆盖</th>
            <th className={cn(HEAD_CLASS, "text-left")}>最近更新时间</th>
            <th className={cn(HEAD_CLASS, "wl-cell-last pr-4 text-right")}>信号</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const { instrument } = item;
            const instId = instrument.inst_id;
            const live = quotes[instId];
            const tone = signalTone(item);
            const signal = signalText(item);
            const change = item.change_pct_24h;
            const [snapshotDate, snapshotTime] = snapshotLines(item.last_candle_at);
            const [coverageMain, coverageNote] = coverageLines(item);

            return (
              <tr
                key={instId}
                onClick={() => navigate(`/watchlist/${instId}`)}
                className="wl-row cursor-pointer border-b transition-colors last:border-0 hover:bg-accent/50"
              >
                <td
                  className="wl-target-cell wl-cell-first py-2 pl-4 pr-2 align-middle"
                  style={{ boxShadow: `inset 3px 0 0 ${TONE_BAR_COLORS[tone]}` }}
                >
                  <Link
                    to={`/watchlist/${instId}`}
                    onClick={(event) => event.stopPropagation()}
                    className="block truncate pr-6 text-sm font-semibold no-underline underline-offset-4 hover:underline"
                    style={{ lineHeight: 1.25 }}
                  >
                    {instId}
                  </Link>
                  <span
                    className="block truncate pr-6 text-[11px] text-muted-foreground"
                    style={{ lineHeight: 1.25 }}
                  >
                    {instrument.product_key} · {instTypeLabel(instrument.inst_type)}
                  </span>
                  <input
                    key={`${instId}:${item.group}:${groupResetToken}`}
                    list="watchlist-groups"
                    defaultValue={item.group}
                    aria-label={`${instId} 的分组`}
                    title="修改后按回车或移开焦点即可换组"
                    disabled={busy === instId}
                    onClick={(event) => event.stopPropagation()}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        event.currentTarget.blur();
                      }
                    }}
                    onBlur={(event) => {
                      const next = event.currentTarget.value.trim() || DEFAULT_GROUP;
                      if (next !== item.group) onMove(instId, next);
                    }}
                    className={GROUP_INPUT_CLASS}
                  />
                  <button
                    type="button"
                    aria-label={`移出 ${instId}`}
                    disabled={busy === instId}
                    onClick={(event) => {
                      event.stopPropagation();
                      onRemove(instId);
                    }}
                    className="wl-remove absolute right-1 top-3 rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-destructive disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </td>

                <td className="px-2 py-1.5 text-right align-middle">
                  <span
                    className="block whitespace-nowrap font-mono text-sm font-semibold tabular-nums"
                    style={{ lineHeight: 1.25 }}
                  >
                    {metricText(live?.last ?? item.last_price, item.data_status)}
                  </span>
                  <span
                    className="mt-1 flex justify-end"
                    title="最近 24 小时 1 小时收盘"
                  >
                    <Sparkline closes={closes[instId] ?? []} />
                  </span>
                </td>

                <td
                  className={cn(
                    "px-1.5 py-2 text-right align-middle font-mono text-xs tabular-nums whitespace-nowrap",
                    change === null ? "text-muted-foreground" : signedTone(change),
                  )}
                >
                  {change === null ? metricText(null, item.data_status) : `${signedValue(change)}%`}
                </td>

                <td className="px-1.5 py-2 align-middle">
                  <span
                    className={cn(
                      "whitespace-nowrap text-xs font-medium",
                      trendTone(item.trend),
                    )}
                  >
                    {trendText(item.trend, item.data_status)}
                  </span>
                </td>

                <td className="px-1.5 py-2 text-right align-middle font-mono text-xs tabular-nums whitespace-nowrap">
                  {metricText(item.rsi_14, item.data_status)}
                </td>

                <td className="px-1.5 py-2 text-right align-middle font-mono text-xs tabular-nums whitespace-nowrap">
                  {item.atr_pct_14 === null
                    ? metricText(null, item.data_status)
                    : `${item.atr_pct_14}%`}
                </td>

                <td className="px-1.5 py-2 align-middle text-xs text-muted-foreground whitespace-nowrap">
                  <span className="block" style={{ lineHeight: 1.25 }}>
                    {coverageMain}
                  </span>
                  {coverageNote === "" ? null : (
                    <span className="block" style={{ lineHeight: 1.25 }}>
                      {coverageNote}
                    </span>
                  )}
                </td>

                <td className="px-1.5 py-2 align-middle text-xs text-muted-foreground whitespace-nowrap">
                  <span className="block" style={{ lineHeight: 1.25 }}>
                    {snapshotDate}
                  </span>
                  <span className="block" style={{ lineHeight: 1.25 }}>
                    {snapshotTime}
                  </span>
                </td>

                <td className="wl-cell-last py-2 pl-2 pr-4 text-right align-middle">
                  <span
                    className={cn(
                      "block truncate text-[11px] font-medium",
                      toneClass(tone),
                    )}
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
    </div>
  );
}
