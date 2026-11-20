import { Trash2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import type { WatchlistItem } from "../../lib/api";
import { signedTone, signedValue } from "../../lib/display";
import type { QuoteUpdate } from "../../lib/stream";
import { cn } from "../../lib/utils";
import { metricText } from "../../lib/watchlist";
import { signalText, signalTone, TONE_BAR_COLORS, toneClass } from "../../lib/watchlist-summary";
import { Sparkline } from "./sparkline";

/**
 * 关注列表：固定 4 列，行高 51px。
 *
 * 列宽与内边距写在 `index.css` 的 `.wl-col-*` / `.wl-table` 里，表头与单元格共用同一组
 * 声明，所以两边的 x 坐标天然一致；24H 列在 ≤900px 由 `.wl-col-24h` 整列隐藏。
 */
export function WatchlistList({
  items,
  quotes,
  closes,
  busy,
  onRemove,
}: {
  items: readonly WatchlistItem[];
  quotes: Readonly<Record<string, QuoteUpdate>>;
  closes: Readonly<Record<string, number[]>>;
  busy: string | null;
  onRemove: (instId: string) => void;
}) {
  const navigate = useNavigate();

  return (
    <table className="wl-table text-sm">
      <colgroup>
        <col className="wl-col-target" />
        <col className="wl-col-24h" />
        <col className="wl-col-price" />
        <col className="wl-col-signal" />
      </colgroup>
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
                  className="block truncate pr-6 text-sm font-semibold no-underline underline-offset-4 hover:underline"
                  style={{ lineHeight: 1.25 }}
                >
                  {instId}
                </Link>
                <span
                  className="block truncate pr-6 text-[11px] text-muted-foreground"
                  style={{ lineHeight: 1.25 }}
                >
                  {instrument.product_key} · {item.group}
                </span>
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
  );
}
