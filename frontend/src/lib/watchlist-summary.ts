/**
 * 自选页「关注汇总」与「信号」列的固定口径。
 *
 * 三块汇总全部在浏览器里按下面这些规则计算，不新增后端接口：
 *
 * - 上涨 = `change_pct_24h > 0`；下跌 = `change_pct_24h < 0`；
 *   其余（等于 0、为 null、或不是合法数字）算「平盘 / 无数据」。
 *   这个标签必须完整写成「平盘 / 无数据」，不能简写成「平盘」——
 *   等于 0 和取不到值在业务上是两件事，只是共用同一个展示桶。
 * - 平均涨跌 = 只对有 `change_pct_24h` 的标的取算术平均；一个都没有时显示 `—`，
 *   不用 0 顶替。
 * - 有信号 = `last_signal != null` 的标的数；不得用「是否有策略」代替。
 * - 有信号 = `last_signal != null` 的标的数；不得用「是否有策略」代替。
 * - 需要处理 = 有信号的标的 + 归属到这些标的的 `GET /api/alerts?status=pending` 条数，
 *   最多展示 6 条，多出来的写「另有 N 项」。
 * - 提醒归属 = 提醒的 `instrument_id` 与自选 `inst_id` 相等，或去掉 `-SWAP` 后缀后相等；
 *   归属不到任何自选标的的提醒不计入本页汇总，它们属于提醒页。
 *
 * 分组筛选是联动的：本模块的入参是「当前分组筛选后的标的列表」，列表与三块汇总用同一个
 * 列表——选中某个分组后两边一起收窄，切回「全部」恢复全量。
 */

import type { AlertItem } from "./alerts";
import type { WatchlistItem } from "./api";

/** 信号色条与信号文字的档位：看多、需注意、无信号。 */
export type WatchlistTone = "bullish" | "attention" | "none";

/** 契约里写死的三段信号色条颜色。 */
export const TONE_BAR_COLORS: Record<WatchlistTone, string> = {
  bullish: "#10b981",
  attention: "#f59e0b",
  none: "#d4d4d8",
};

export function toneClass(tone: WatchlistTone): string {
  if (tone === "bullish") return "text-emerald-600 dark:text-emerald-400";
  if (tone === "attention") return "text-amber-600 dark:text-amber-400";
  return "text-muted-foreground";
}

export type ChangeBucket = "up" | "down" | "flat";

/** 堆叠条与三段计数的固定顺序：上涨、下跌、平盘 / 无数据。 */
export const CHANGE_BUCKETS: readonly ChangeBucket[] = ["up", "down", "flat"];

export const CHANGE_BUCKET_LABELS: Record<ChangeBucket, string> = {
  up: "上涨",
  down: "下跌",
  flat: "平盘 / 无数据",
};

export const CHANGE_BUCKET_COLORS: Record<ChangeBucket, string> = {
  up: "#10b981",
  down: "#ef4444",
  flat: "#d4d4d8",
};

export function changeBucket(changePct24h: string | null): ChangeBucket {
  if (changePct24h === null) return "flat";
  const value = Number(changePct24h);
  if (!Number.isFinite(value) || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}

/**
 * `last_signal` 为 null / undefined 一律是「无信号」。
 * `HOLD` 不是看多也不是需注意，同样归到「无信号」。
 */
export function signalTone(item: Pick<WatchlistItem, "last_signal">): WatchlistTone {
  const action = item.last_signal?.action;
  if (action === "BUY") return "bullish";
  if (action === "SELL") return "attention";
  return "none";
}

/** 信号列只显示一行文字：有解释就用解释，没有解释才用动作本身的档位名。 */
export function signalText(item: Pick<WatchlistItem, "last_signal">): string {
  const signal = item.last_signal;
  if (signal === null || signal === undefined) return "无信号";
  if (signal.action === "HOLD") return "无信号";
  const reason = signal.reason.trim();
  if (reason !== "") return reason;
  return signal.action === "BUY" ? "看多" : "需注意";
}

export type WatchlistAggregate = {
  /** 参与聚合的标的数，等于 `items.length`。 */
  total: number;
  /** `last_signal != null` 的标的数。 */
  signalCount: number;
  /** 有 change_pct_24h 的标的的算术平均；一个都没有时为 null。 */
  averageChangePct: number | null;
  distribution: Record<ChangeBucket, number>;
};

export function aggregateWatchlist(items: readonly WatchlistItem[]): WatchlistAggregate {
  const distribution: Record<ChangeBucket, number> = { up: 0, down: 0, flat: 0 };
  const changes: number[] = [];
  let signalCount = 0;

  for (const item of items) {
    distribution[changeBucket(item.change_pct_24h)] += 1;

    if (item.change_pct_24h !== null) {
      const value = Number(item.change_pct_24h);
      if (Number.isFinite(value)) changes.push(value);
    }

    if (item.last_signal !== null && item.last_signal !== undefined) signalCount += 1;
  }

  const averageChangePct =
    changes.length === 0 ? null : changes.reduce((sum, value) => sum + value, 0) / changes.length;

  return { total: items.length, signalCount, averageChangePct, distribution };
}

/** 平均涨跌固定两位小数；没有可算的值时写 `—`，不补 0。 */
export function averageChangeText(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(2)}%`;
}

/** 「平均涨跌」数值的正负配色；取不到值时不着色。 */
export function averageChangeTone(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}

export type PendingEntry = {
  key: string;
  /** 左侧主体：标的名，提醒没有关联标的时写「全局」。 */
  label: string;
  /** 右侧说明：信号解释或提醒标题。 */
  detail: string;
  tone: WatchlistTone;
};

export type PendingDigest = {
  /** 需要处理的总条数，等于信号数 + 待处理提醒数。 */
  total: number;
  /** 实际展示的条目，最多 `PENDING_VISIBLE_LIMIT` 条。 */
  entries: PendingEntry[];
  /** 超出展示上限的条数，0 表示没有。 */
  overflow: number;
};

export const PENDING_VISIBLE_LIMIT = 6;

/** 提醒的级别只区分「要不要人看一眼」，不做颜色分级。 */
function alertTone(severity: string | null | undefined): WatchlistTone {
  if (severity === "critical" || severity === "warning") return "attention";
  return "none";
}

/** 去掉永续合约的 `-SWAP` 后缀；现货标识原样返回。 */
export function stripSwapSuffix(instId: string): string {
  return instId.endsWith("-SWAP") ? instId.slice(0, -"-SWAP".length) : instId;
}

/**
 * 提醒归属：返回这条提醒属于哪个自选标的的 `inst_id`，归属不到返回 null。
 *
 * 真实数据里提醒挂的是 `BTC-USDT`，自选里是 `BTC-USDT-SWAP`，所以先做精确匹配再退到
 * 去掉 `-SWAP` 后缀的匹配。两边可能同时存在（`XAAPL-USDT` 与 `AAPL-USDT-SWAP`），
 * 精确匹配优先，避免把现货标的的提醒算到同产品的永续上。
 */
export function watchlistOwner(
  items: readonly WatchlistItem[],
  alertInstrumentId: string | null | undefined,
): string | null {
  if (alertInstrumentId === null || alertInstrumentId === undefined) return null;
  if (items.some((item) => item.instrument.inst_id === alertInstrumentId)) {
    return alertInstrumentId;
  }
  const owner = items.find(
    (item) => stripSwapSuffix(item.instrument.inst_id) === alertInstrumentId,
  );
  return owner === undefined ? null : owner.instrument.inst_id;
}

export function buildPendingDigest(
  items: readonly WatchlistItem[],
  alerts: readonly AlertItem[],
  limit: number = PENDING_VISIBLE_LIMIT,
): PendingDigest {
  const fromSignals: PendingEntry[] = items
    .filter((item) => item.last_signal !== null && item.last_signal !== undefined)
    .map((item) => ({
      key: `signal:${item.instrument.inst_id}`,
      label: item.instrument.inst_id,
      detail: signalText(item),
      tone: signalTone(item),
    }));

  const fromAlerts: PendingEntry[] = [];
  for (const alert of alerts) {
    const owner = watchlistOwner(items, alert.instrument_id);
    // 归属不到任何自选标的的提醒不属于本页汇总，它们归提醒页统计。
    if (owner === null) continue;
    fromAlerts.push({
      key: `alert:${alert.id}`,
      label: owner,
      detail: alert.title,
      tone: alertTone(alert.severity),
    });
  }

  const all = [...fromSignals, ...fromAlerts];
  return {
    total: all.length,
    entries: all.slice(0, limit),
    overflow: Math.max(0, all.length - limit),
  };
}
