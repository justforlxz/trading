/**
 * 持仓页的只读客户端与展示文案。
 *
 * 账户与交易所持仓的数值全部来自后端快照；这里不计算盈亏、名义价值、
 * 保证金比例或今日盈亏，只把契约里的字符串原样交给页面。
 */

import type { components } from "../api/types";
import { request } from "./api";
import { formatBeijingTime, percentValue, signedValue } from "./display";
import {
  isAtLeast,
  updateTime,
  type AccountUpdate,
  type PositionUpdate,
} from "./stream";

export type AccountSummary = components["schemas"]["AccountSummaryResponse"];
export type AccountSync = components["schemas"]["AccountSyncResponse"];
export type ExchangePositions = components["schemas"]["ExchangePositionsResponse"];
export type ExchangePosition = ExchangePositions["items"][number];
export type AccountStatus = AccountSummary["status"];

export const MISSING_VALUE = "未提供";

export function fetchAccountSummary(): Promise<AccountSummary> {
  return request<AccountSummary>("/account/summary");
}

/** 只触发 OKX 只读快照同步，不产生任何订单。 */
export function syncAccount(): Promise<AccountSync> {
  return request<AccountSync>("/account/sync", { method: "POST" });
}

export function fetchExchangePositions(): Promise<ExchangePositions> {
  return request<ExchangePositions>("/positions/exchange");
}

export function valueOrMissing(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return MISSING_VALUE;
  return value;
}

/** 账户来源用文字区分 REST 快照与 WebSocket 推送，避免混成同一个来源。 */
export function accountSourceLabel(source: string | null | undefined): string {
  if (source === null || source === undefined || source.trim() === "") return MISSING_VALUE;
  if (source === "okx_rest") return "OKX REST 快照";
  if (source === "okx_ws") return "OKX WebSocket 推送";
  return source;
}

export function accountStatusLabel(status: AccountStatus): string {
  if (status === "unconfigured") return "未配置 OKX 密钥";
  if (status === "stale") return "快照已过期";
  return "正常";
}

export function positionSideLabel(side: ExchangePosition["pos_side"]): string {
  return side === "short" ? "空" : "多";
}

export function marginModeLabel(mode: string | null | undefined): string {
  if (mode === null || mode === undefined || mode.trim() === "") return MISSING_VALUE;
  if (mode === "cross") return "全仓";
  if (mode === "isolated") return "逐仓";
  return mode;
}

/** 后端已经按百分数返回，这里只补单位，不再乘以 100。 */
export function marginUsageText(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return MISSING_VALUE;
  return `${value}%`;
}

/** 契约里的 `upl_ratio` 是比率（0.0204 表示 2.04%），展示层只做单位换算。 */
export function uplRatioText(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return MISSING_VALUE;
  return percentValue(value);
}

/** 盈亏类字段按契约原值展示，只补正负号。 */
export function pnlText(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return MISSING_VALUE;
  return signedValue(value);
}

/** 用推送里的持仓字段覆盖 HTTP 快照；推送没有的字段继续保留快照值。 */
export function mergePositionUpdates(
  positions: ExchangePositions,
  updates: Record<string, PositionUpdate>,
): ExchangePositions {
  let changed = false;
  const snapshotAsOf = positions.as_of ?? null;
  let asOf = snapshotAsOf;
  const items = positions.items.map((item) => {
    const update = updates[item.pos_id];
    if (update === undefined) return item;
    const moment = updateTime(update);
    if (!isAtLeast(moment, snapshotAsOf)) return item;
    const timeMoved = moment !== null && (asOf === null || moment > asOf);
    if (timeMoved) asOf = moment;
    const merged = {
      ...item,
      mark_px: update.mark_px ?? item.mark_px,
      upl: update.upl ?? item.upl,
      upl_ratio: update.upl_ratio ?? item.upl_ratio,
    };
    const valuesMoved =
      merged.mark_px !== item.mark_px ||
      merged.upl !== item.upl ||
      merged.upl_ratio !== item.upl_ratio;
    if (!valuesMoved && !timeMoved) return item;
    changed = true;
    return valuesMoved ? merged : item;
  });
  return changed ? { ...positions, items, as_of: asOf } : positions;
}

/**
 * 推送账户快照只覆盖它携带的字段；日盈亏基准等 HTTP 字段继续保留。
 *
 * 推送不携带持仓市值，`position_notional` 与 `position_notional_at` 必须继续作为
 * 同一份 HTTP 快照保留；账户快照时间前进时，不能把旧市值改标成新时间。
 */
export function mergeAccountUpdate(
  account: AccountSummary,
  update: AccountUpdate | null,
): AccountSummary {
  if (update === null) return account;
  const moment = updateTime(update);
  if (!isAtLeast(moment, account.captured_at ?? null)) return account;
  return {
    ...account,
    account_id: update.account_id || account.account_id,
    currency: update.currency ?? account.currency,
    equity: update.equity ?? account.equity,
    available_equity: update.available_equity ?? account.available_equity,
    cash_balance: update.cash_balance ?? account.cash_balance,
    unrealized_pnl: update.unrealized_pnl ?? account.unrealized_pnl,
    used_margin: update.used_margin ?? account.used_margin,
    available_margin: update.available_margin ?? account.available_margin,
    margin_usage_pct: update.margin_usage_pct ?? account.margin_usage_pct,
    captured_at: moment ?? account.captured_at,
    source: update.source ?? account.source,
  };
}

// ---------------------------------------------------------------- 重做后的持仓页

export type EquityRange = "1d" | "1w" | "1m" | "6m" | "1y";
export type PositionCards = components["schemas"]["PositionCardsResponse"];
export type PositionCard = PositionCards["items"][number];
export type EquityCurve = components["schemas"]["EquityCurveResponse"];
export type CurvePoint = components["schemas"]["CurvePointItem"];
export type OrderHistory = components["schemas"]["OrderHistoryResponse"];
export type OrderHistoryItem = OrderHistory["items"][number];
export type OrderScope = NonNullable<OrderHistory["scope"]>;
export type StopStatus = PositionCard["stop_status"];

/** 资产卡上的五个区间；`key` 直接作为查询参数，后端按同一套键解析。 */
export const EQUITY_RANGES: readonly { key: EquityRange; label: string }[] = [
  { key: "1d", label: "1 天" },
  { key: "1w", label: "1 周" },
  { key: "1m", label: "1 月" },
  { key: "6m", label: "半年" },
  { key: "1y", label: "1 年" },
];

export const ORDER_SCOPES: readonly { key: OrderScope; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "open", label: "挂单" },
  { key: "history", label: "历史" },
];

export function fetchPositionCards(range: EquityRange): Promise<PositionCards> {
  return request<PositionCards>(`/positions/cards?range=${range}`);
}

export function fetchEquityCurve(range: EquityRange): Promise<EquityCurve> {
  return request<EquityCurve>(`/account/equity-curve?range=${range}`);
}

export function fetchInstrumentOrders(
  instId: string,
  scope: OrderScope,
): Promise<OrderHistory> {
  return request<OrderHistory>(
    `/positions/${encodeURIComponent(instId)}/orders?scope=${scope}`,
  );
}

/** 止损三态：`unavailable` 必须说成「未取到」，不能与「未挂止损」混成一句。 */
export function stopStatusLabel(status: StopStatus): string {
  if (status === "confirmed") return "已设止损";
  if (status === "unavailable") return "未取到";
  return "未挂止损";
}

/** 徽标色调：有止损用正常色，确认没挂用警示色，没取到用中性色。 */
export function stopStatusTone(status: StopStatus): string {
  if (status === "confirmed") {
    return "border-emerald-600/40 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400";
  }
  if (status === "none") {
    return "border-rose-600/40 bg-rose-500/5 text-rose-700 dark:text-rose-400";
  }
  return "border-border text-muted-foreground";
}

/** 名义合计不完整时数字前标 `≥`：已知部分不是全部。 */
export function notionalPrefix(status: "exact" | "partial" | null | undefined): string {
  return status === "partial" ? "≥" : "";
}

export function marginUsageFloorPrefix(isFloor: boolean | null | undefined): string {
  return isFloor === false ? "" : "≥";
}

export type CurveGeometry = {
  line: string;
  direction: "up" | "down";
};

/**
 * 把一串十进制字符串点映射成 SVG 折线与填充区。
 *
 * 只做几何换算，不改数值含义：点少于两个时返回 `null`，调用方据此不渲染任何折线
 * ——画一条假线比空着更糟。
 */
export function curveGeometry(
  points: readonly { value: string }[],
  width: number,
  height: number,
  padding = 3,
): CurveGeometry | null {
  if (points.length < 2) return null;
  const values = points.map((point) => Number(point.value));
  if (values.some((value) => !Number.isFinite(value))) return null;
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const step = (width - padding * 2) / (points.length - 1);
  const line = values
    .map((value, index) => {
      const x = padding + index * step;
      const y = height - padding - ((value - low) / span) * (height - padding * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return {
    line,
    direction: values[values.length - 1] >= values[0] ? "up" : "down",
  };
}

/** 曲线方向对应的描边色：与项目现有的涨跌成对写法一致。 */
export function curveStroke(direction: "up" | "down"): string {
  return direction === "up" ? "#059669" : "#e11d48";
}

/** 订单方向文案。 */
export function orderSideLabel(side: OrderHistoryItem["side"]): string {
  return side === "sell" ? "卖出" : "买入";
}

/** 订单状态：上游状态字面量到中文；未知状态原样显示，不猜。 */
export function orderStatusLabel(status: string): string {
  if (status === "filled") return "已成交";
  if (status === "live") return "挂单中";
  if (status === "partially_filled") return "部分成交";
  if (status === "canceled") return "已撤销";
  if (status === "effective") return "已生效";
  return status;
}

/** 曲线不可用时给用户的具体原因，带上快照起始时刻。 */
export function curveUnavailableText(firstSnapshotAt: string | null | undefined): string {
  if (firstSnapshotAt === null || firstSnapshotAt === undefined) {
    return "这段区间还没有数据（账户快照尚未开始记录）";
  }
  return `这段区间还没有数据（快照自 ${formatBeijingTime(firstSnapshotAt, false)} 起记录）`;
}

/**
 * 把推送里的价格与盈亏覆盖到卡片上；止损状态、占比与曲线保持 HTTP 快照。
 *
 * 推送不带止损与曲线，覆盖它们会得到「未取到」与空曲线——比不更新更糟。
 * 止损**距离**是标记价的函数：标记价一更新它就过期，因此一并清空，卡片只显示
 * 止损价位，等下一次 HTTP 快照再把距离补回来。同一张卡上不留两份互相矛盾的数。
 */
export function mergeCardUpdates(
  cards: PositionCards,
  updates: Record<string, PositionUpdate>,
): PositionCards {
  let changed = false;
  let asOf = cards.as_of ?? null;
  const items = cards.items.map((card) => {
    const update = updates[card.pos_id];
    if (update === undefined) return card;
    const moment = updateTime(update);
    if (!isAtLeast(moment, cards.as_of ?? null)) return card;
    const markMoved = update.mark_px != null && update.mark_px !== card.mark_px;
    const merged = {
      ...card,
      mark_px: update.mark_px ?? card.mark_px,
      upl: update.upl ?? card.upl,
      upl_ratio: update.upl_ratio ?? card.upl_ratio,
      stop_distance_pct: markMoved ? null : card.stop_distance_pct,
    };
    if (
      merged.mark_px === card.mark_px &&
      merged.upl === card.upl &&
      merged.upl_ratio === card.upl_ratio &&
      merged.stop_distance_pct === card.stop_distance_pct
    ) {
      return card;
    }
    changed = true;
    if (moment !== null && (asOf === null || moment > asOf)) asOf = moment;
    return merged;
  });
  return changed ? { ...cards, items, as_of: asOf } : cards;
}

/**
 * 金额、价格与百分比的显示格式。
 *
 * 契约里的十进制以字符串返回，除法算出来的字段会带十几位小数（`51.254667634136`）。
 * 这里只做**显示取整**：数值含义、正负与量级都不改，也不参与任何判断——判断用后端
 * 给的原值。千分位只为可读性，`en-US` 分组与已批准的原型一致。
 */
function withGroups(
  value: string | null | undefined,
  minimumFractionDigits: number,
  maximumFractionDigits: number,
): string {
  if (value === null || value === undefined || value.trim() === "") return MISSING_VALUE;
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return number.toLocaleString("en-US", { minimumFractionDigits, maximumFractionDigits });
}

/** 金额：固定两位小数，`413.45` / `1,786.39`。 */
export function amountText(value: string | null | undefined, digits = 2): string {
  return withGroups(value, digits, digits);
}

/** 价格：不补零，最多四位小数，`60,470` / `1,717.3` / `276.71`。 */
export function priceText(value: string | null | undefined): string {
  return withGroups(value, 0, 4);
}

/** 带正负号的金额；0 不加号，避免「+0.00」看起来像有收益。 */
export function signedAmountText(value: string | null | undefined, digits = 2): string {
  const text = amountText(value, digits);
  if (text === MISSING_VALUE) return text;
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) return text;
  return number > 0 ? `+${text}` : text;
}

/** 百分比：后端已经按百分数返回，这里只取整并补 `%`。 */
export function percentText(value: string | null | undefined, digits = 1): string {
  const text = withGroups(value, 0, digits);
  return text === MISSING_VALUE ? text : `${text}%`;
}
