import type { AlertItem, WatchlistItem } from "../../lib/api";

/** 自选页测试用的标的与提醒样本：字段形状对齐 `WatchlistItem` / `AlertItem` 契约。 */

export function makeSignal(
  action: NonNullable<WatchlistItem["last_signal"]>["action"],
  reason: string,
): NonNullable<WatchlistItem["last_signal"]> {
  return {
    action,
    bar: "1h",
    generated_at: "2026-11-10T07:00:00Z",
    inst_id: "AAPL-USDT-SWAP",
    inst_type: "SWAP",
    price: "100.00",
    reason,
    signal_id: "sig_0001",
    strategy_instance_id: "si_0001",
  };
}

export function makeItem(
  instId: string,
  options: {
    change?: string | null;
    signal?: WatchlistItem["last_signal"];
    group?: string;
    dataStatus?: WatchlistItem["data_status"];
    strategy?: WatchlistItem["strategy"];
    instType?: WatchlistItem["instrument"]["inst_type"];
    assetType?: WatchlistItem["instrument"]["asset_type"];
  } = {},
): WatchlistItem {
  return {
    atr_pct_14: "2.3",
    candle_count: 120,
    change_pct_24h: options.change === undefined ? "1.00" : options.change,
    data_status: options.dataStatus ?? "ok",
    group: options.group ?? "默认",
    instrument: {
      asset_type: options.assetType ?? "tokenized_equity",
      base_currency: "AAPL",
      inst_id: instId,
      inst_type: options.instType ?? "SWAP",
      product_key: "AAPL",
      quote_currency: "USDT",
      trading_status: "live",
    },
    last_candle_at: "2026-11-12T16:00:00Z",
    last_price: "100.00",
    last_signal: options.signal ?? null,
    rsi_14: "55.4",
    strategy: options.strategy ?? null,
    trend: "bullish",
    volume_24h_quote: "1000000",
  };
}

export function makeAlert(id: string, title: string, instrumentId: string | null): AlertItem {
  return {
    detail: `${title} 的说明`,
    id,
    instrument_id: instrumentId,
    payload: {},
    rule_id: "rule_0001",
    rule_version: "v1",
    severity: "warning",
    status: "pending",
    title,
    triggered_at: "2026-11-10T23:00:00Z",
    type: "risk",
  };
}
