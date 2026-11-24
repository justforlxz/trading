/**
 * 首页「关注列表」卡片的置顶逻辑。
 *
 * 置顶清单存在服务端设置文档的 `display.homepage_pinned` 里：字符串数组、按选择
 * 顺序、最多 5 个、元素必须在自选里（写入校验在 `backend/app/settings`）。
 *
 * 页面读取时只与当前自选**求交集**：从自选删掉的置顶项不再显示，但库里那份清单
 * 不改写——把它加回自选后，同一份置顶清单会自动恢复显示。
 */

import type { components } from "../api/types";
import type { WatchlistItem } from "./api";

type DashboardWatchlistItem = components["schemas"]["DashboardWatchlistItem"];

/** 汇总行里卡片真正会读的几列：只声明这些，免得调用方为了类型补齐用不到的字段。 */
type SummaryQuote = Pick<
  DashboardWatchlistItem,
  "inst_id" | "display_symbol" | "name" | "last_price" | "change_pct_24h" | "rsi_14" | "trend"
>;

/**
 * 一行候选：弹窗里的可选标的，也是卡片一行的数据来源。
 *
 * 卡片与弹窗共用同一份候选（`GET /api/watchlist` 的整份自选）：首页汇总模块只带
 * 五行，拿它当卡片行的来源时，置顶到第 6、第 7 个标的上会「保存了却看不见」。
 */
export type PinnedCandidate = {
  inst_id: string;
  /** 展示名（`product_key`，例如 AAPL）；有汇总数据时用汇总里更具体的写法。 */
  display_symbol: string;
  /** 卡片副行与弹窗副行共用的名称（`product_key`）。 */
  name: string;
  /** 弹窗副行里的分组名。 */
  detail: string;
  last_price: string | null;
  change_pct_24h: string | null;
  rsi_14: string | null;
  trend: DashboardWatchlistItem["trend"];
};

/** 首页卡片最多置顶几个标的；与服务端 `HOMEPAGE_PINNED_LIMIT` 固定一致。 */
export const PINNED_LIMIT = 5;

/**
 * `GET /api/watchlist` 的行 → 弹窗候选。
 *
 * 候选必须覆盖整份自选：首页汇总模块只带五行，用它当候选会让「勾满 5 个后其余项
 * 变灰」永远看不到，也选不到第 6 个标的。
 */
export function pinnedCandidates(items: readonly WatchlistItem[]): PinnedCandidate[] {
  return items.map((item) => ({
    inst_id: item.instrument.inst_id,
    display_symbol: item.instrument.product_key,
    name: item.instrument.product_key,
    detail: item.group,
    last_price: item.last_price,
    change_pct_24h: item.change_pct_24h,
    rsi_14: item.rsi_14,
    trend: item.trend,
  }));
}

/**
 * 卡片要显示的行：按置顶顺序取自选候选，价格与指标用首页汇总里那一份覆盖。
 *
 * 顺序与取舍只由「置顶清单 ∩ 当前自选」决定，**不依赖首页汇总**：汇总模块只带五行，
 * 用它当行的来源时，置顶到第 6、第 7 个标的上会保存成功却渲染不出来。汇总只提供
 * 更实时的数值（推送会写回汇总里的行），拿不到就退回自选快照。
 */
export function pinnedCardRows(
  candidates: readonly PinnedCandidate[],
  summaryRows: readonly SummaryQuote[],
  pinned: readonly string[],
): PinnedCandidate[] {
  const byInstId = new Map(summaryRows.map((row) => [row.inst_id, row]));
  return pinnedItems(candidates, pinned).map((row) => {
    const live = byInstId.get(row.inst_id);
    if (live === undefined) return row;
    return {
      ...row,
      display_symbol: live.display_symbol,
      name: live.name,
      last_price: live.last_price ?? row.last_price,
      change_pct_24h: live.change_pct_24h ?? row.change_pct_24h,
      rsi_14: live.rsi_14 ?? row.rsi_14,
      trend: live.trend ?? row.trend,
    };
  });
}

/**
 * 提交给接口的置顶清单：只保留当前自选里的标识。
 *
 * 后端要求「元素必须在自选里」，而草稿里可能还留着已从自选删掉的置顶项（它们要被保留在
 * 库里，但不能由这次请求提交）；服务端会在写库时按它自己知道的自选清单把那些项补回去。
 */
export function submittablePinned(
  draft: readonly string[],
  candidates: readonly { inst_id: string }[],
): string[] {
  const available = new Set(candidates.map((item) => item.inst_id));
  return draft.filter((instId) => available.has(instId));
}

/** 按置顶顺序取当前自选里仍然存在的标的；不在自选里的项跳过，不回写库。 */
export function pinnedItems<T extends { inst_id: string }>(
  items: readonly T[],
  pinned: readonly string[],
): T[] {
  const byInstId = new Map(items.map((item) => [item.inst_id, item]));
  const picked: T[] = [];
  for (const instId of pinned) {
    const item = byInstId.get(instId);
    if (item !== undefined) picked.push(item);
  }
  return picked;
}

/**
 * 勾选或取消一个标的，返回新的清单（不改原数组）。
 *
 * 已经在清单里就移除；不在且没满 5 个就追加到末尾（追加顺序即选择顺序）；已满
 * 5 个时保持原样——弹窗里同时会把其余项禁用，这里是纯函数的兜底。
 */
export function togglePinned(pinned: readonly string[], instId: string): string[] {
  if (pinned.includes(instId)) return pinned.filter((item) => item !== instId);
  if (pinned.length >= PINNED_LIMIT) return [...pinned];
  return [...pinned, instId];
}

/** 数量文案，例如「已选 3/5」；弹窗底部与卡片元信息行共用。 */
export function pinnedCountText(count: number): string {
  return `已选 ${count}/${PINNED_LIMIT}`;
}

/** 已满 5 个：弹窗里未勾选的项变灰禁用，并提示先取消一个。 */
export function isPinnedFull(pinned: readonly string[]): boolean {
  return pinned.length >= PINNED_LIMIT;
}
