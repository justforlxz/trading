import { describe, expect, it } from "vitest";

import {
  accountSourceLabel,
  accountStatusLabel,
  marginModeLabel,
  marginUsageText,
  mergeAccountUpdate,
  mergePositionUpdates,
  MISSING_VALUE,
  pnlText,
  positionSideLabel,
  type AccountSummary,
  type ExchangePositions,
  uplRatioText,
  valueOrMissing,
} from "./positions";
import type { AccountUpdate, PositionUpdate } from "./stream";

describe("持仓展示文案", () => {
  it("缺失值统一显示「未提供」", () => {
    expect(valueOrMissing(null)).toBe(MISSING_VALUE);
    expect(valueOrMissing(undefined)).toBe(MISSING_VALUE);
    expect(valueOrMissing("  ")).toBe(MISSING_VALUE);
    expect(valueOrMissing("1248.60")).toBe("1248.60");
  });

  it("OKX REST 与 WebSocket 来源用不同文字区分", () => {
    expect(accountSourceLabel("okx_rest")).toBe("OKX REST 快照");
    expect(accountSourceLabel("okx_ws")).toBe("OKX WebSocket 推送");
    expect(accountSourceLabel("other_source")).toBe("other_source");
    expect(accountSourceLabel(null)).toBe(MISSING_VALUE);
  });

  it("账户状态、方向与保证金模式使用可读文字", () => {
    expect(accountStatusLabel("ok")).toBe("正常");
    expect(accountStatusLabel("stale")).toBe("快照已过期");
    expect(accountStatusLabel("unconfigured")).toBe("未配置 OKX 密钥");
    expect(positionSideLabel("long")).toBe("多");
    expect(positionSideLabel("short")).toBe("空");
    expect(marginModeLabel("cross")).toBe("全仓");
    expect(marginModeLabel("isolated")).toBe("逐仓");
    expect(marginModeLabel(null)).toBe(MISSING_VALUE);
  });

  it("保证金使用率只补单位，不重新换算", () => {
    expect(marginUsageText("45.36")).toBe("45.36%");
    expect(marginUsageText(null)).toBe(MISSING_VALUE);
  });

  it("盈亏率把契约比率换算成百分数，盈亏值只补正负号", () => {
    expect(uplRatioText("0.0204")).toBe("+2.04%");
    expect(uplRatioText("-0.0204")).toBe("-2.04%");
    expect(uplRatioText(null)).toBe(MISSING_VALUE);
    expect(pnlText("36.96")).toBe("+36.96");
    expect(pnlText("-1.2")).toBe("-1.2");
    expect(pnlText(undefined)).toBe(MISSING_VALUE);
  });
});

const POSITIONS: ExchangePositions = {
  as_of: "2026-11-13T09:00:00Z",
  status: "ok",
  items: [
    {
      asset_class: "tokenized_equity",
      avg_px: "226.80",
      display_symbol: "AAPL-USDT",
      inst_id: "AAPL-USDT-SWAP",
      lever: "3",
      mark_px: "231.42",
      name: "AAPL",
      pos_id: "123456",
      pos_side: "long",
      size: "8",
      upl: "36.96",
      upl_ratio: "0.0204",
    },
  ],
};

const POSITION_UPDATE: PositionUpdate = {
  pos_id: "123456",
  inst_id: "AAPL-USDT-SWAP",
  display_symbol: "AAPL-USDT",
  name: "AAPL",
  asset_class: "tokenized_equity",
  pos_side: "long",
  size: "8",
  avg_px: "226.80",
  mark_px: "233.10",
  upl: "50.40",
  upl_ratio: "0.0278",
  lever: "3",
  mgn_mode: "cross",
  liq_px: "151.20",
  margin: "604.80",
  as_of: "2026-11-14T10:00:00Z",
  received_at: "2026-11-14T10:00:01Z",
};

describe("推送数据合并", () => {
  it("用推送的价格与盈亏覆盖 HTTP 快照，其余字段保持快照值", () => {
    const merged = mergePositionUpdates(POSITIONS, { "123456": POSITION_UPDATE });

    expect(merged.as_of).toBe("2026-11-14T10:00:00Z");
    expect(merged.items[0]).toMatchObject({
      mark_px: "233.10",
      upl: "50.40",
      upl_ratio: "0.0278",
      avg_px: "226.80",
      lever: "3",
    });
  });

  it("没有匹配推送时返回原对象，不制造新快照", () => {
    expect(mergePositionUpdates(POSITIONS, {})).toBe(POSITIONS);
    expect(mergePositionUpdates(POSITIONS, { other: POSITION_UPDATE })).toBe(POSITIONS);
  });

  it("忽略早于 HTTP 快照的推送，避免同步后回退", () => {
    const stale: PositionUpdate = {
      ...POSITION_UPDATE,
      as_of: "2026-11-13T08:00:00Z",
      received_at: "2026-11-13T08:00:01Z",
      mark_px: "9.99",
    };

    expect(mergePositionUpdates(POSITIONS, { "123456": stale })).toBe(POSITIONS);
  });

  it("账户推送只覆盖推送携带的字段，日盈亏基准等字段保留", () => {
    const account: AccountSummary = {
      account_id: "okx-main",
      currency: "USDT",
      day_pnl: "12.30",
      day_pnl_basis: "equity_only",
      equity: "1248.60",
      source: "okx_rest",
      status: "ok",
    };
    const update: AccountUpdate = {
      account_id: "okx-main",
      currency: "USDT",
      equity: "1300.10",
      available_equity: "700.20",
      cash_balance: "0",
      unrealized_pnl: "40.10",
      used_margin: "599.90",
      available_margin: "700.20",
      margin_usage_pct: "46.15",
      captured_at: "2026-11-14T10:00:00Z",
      source: "okx_ws",
      as_of: "2026-11-14T10:00:00Z",
      received_at: "2026-11-14T10:00:01Z",
    };

    expect(mergeAccountUpdate(account, update)).toMatchObject({
      equity: "1300.10",
      source: "okx_ws",
      captured_at: "2026-11-14T10:00:00Z",
      day_pnl: "12.30",
      day_pnl_basis: "equity_only",
      status: "ok",
    });
    expect(mergeAccountUpdate(account, null)).toBe(account);
  });

  it("忽略早于 HTTP 账户快照的推送，避免同步后回退", () => {
    const account: AccountSummary = {
      account_id: "okx-main",
      captured_at: "2026-11-14T10:00:00Z",
      currency: "USDT",
      day_pnl_basis: "equity_only",
      equity: "1300.10",
      status: "ok",
    };
    const stale: AccountUpdate = {
      account_id: "okx-main",
      currency: "USDT",
      equity: "1200.00",
      available_equity: null,
      cash_balance: null,
      unrealized_pnl: null,
      used_margin: null,
      available_margin: null,
      margin_usage_pct: null,
      captured_at: "2026-11-14T09:00:00Z",
      source: "okx_ws",
      as_of: "2026-11-14T09:00:00Z",
      received_at: "2026-11-14T09:00:01Z",
    };

    expect(mergeAccountUpdate(account, stale)).toBe(account);
  });
});
