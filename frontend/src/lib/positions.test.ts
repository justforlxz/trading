import { describe, expect, it } from "vitest";

import {
  accountSourceLabel,
  amountText,
  accountStatusLabel,
  curveGeometry,
  curveUnavailableText,
  marginModeLabel,
  marginUsageFloorPrefix,
  marginUsageText,
  mergeAccountUpdate,
  mergeCardUpdates,
  mergePositionUpdates,
  MISSING_VALUE,
  notionalPrefix,
  orderSideLabel,
  orderStatusLabel,
  percentText,
  pnlText,
  priceText,
  positionSideLabel,
  signedAmountText,
  stopStatusLabel,
  stopStatusTone,
  type AccountSummary,
  type ExchangePositions,
  type PositionCards,
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
      notional_status: "exact",
      margin_usage_floor: false,
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

  it("账户推送前进快照时间时，持仓市值仍保留自己的旧时间", () => {
    const account: AccountSummary = {
      account_id: "okx-main",
      captured_at: "2026-11-14T10:00:00Z",
      currency: "USDT",
      day_pnl_basis: "equity_only",
      equity: "1248.60",
      position_notional: "1851.36",
      position_notional_at: "2026-11-14T10:00:00Z",
      source: "okx_rest",
      status: "ok",
      notional_status: "exact",
      margin_usage_floor: false,
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
      captured_at: "2026-11-14T10:05:00Z",
      source: "okx_ws",
      as_of: "2026-11-14T10:05:00Z",
      received_at: "2026-11-14T10:05:01Z",
    };

    const merged = mergeAccountUpdate(account, update);

    expect(merged.captured_at).toBe("2026-11-14T10:05:00Z");
    expect(merged.position_notional).toBe("1851.36");
    expect(merged.position_notional_at).toBe("2026-11-14T10:00:00Z");
  });

  it("忽略早于 HTTP 账户快照的推送，避免同步后回退", () => {
    const account: AccountSummary = {
      account_id: "okx-main",
      captured_at: "2026-11-14T10:00:00Z",
      currency: "USDT",
      day_pnl_basis: "equity_only",
      equity: "1300.10",
      status: "ok",
      notional_status: "exact",
      margin_usage_floor: false,
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

describe("曲线几何", () => {
  it("少于两个点就不给几何数据：画不出线，也就不画", () => {
    expect(curveGeometry([], 132, 40)).toBeNull();
    expect(curveGeometry([{ value: "1" }], 132, 40)).toBeNull();
  });

  it("首尾点落在左右边界上，方向由首尾大小决定", () => {
    const up = curveGeometry([{ value: "1" }, { value: "2" }, { value: "3" }], 100, 40, 0);
    const down = curveGeometry([{ value: "3" }, { value: "2" }, { value: "1" }], 100, 40, 0);

    expect(up).not.toBeNull();
    expect(up!.line.split(" ")).toHaveLength(3);
    expect(up!.line.startsWith("0.0,")).toBe(true);
    expect(up!.line.endsWith(",0.0")).toBe(true);
    expect(up!.direction).toBe("up");
    expect(down!.direction).toBe("down");
  });

  it("数值非法时返回 null，不画一条乱线", () => {
    expect(curveGeometry([{ value: "abc" }, { value: "1" }], 100, 40)).toBeNull();
  });
});

describe("止损三态文案", () => {
  it("三种状态各有自己的说法", () => {
    expect(stopStatusLabel("confirmed")).toBe("已设止损");
    expect(stopStatusLabel("none")).toBe("未挂止损");
    expect(stopStatusLabel("unavailable")).toBe("未取到");
  });

  it("未取到与未挂止损不能共用同一句", () => {
    expect(stopStatusLabel("unavailable")).not.toBe(stopStatusLabel("none"));
    expect(stopStatusTone("unavailable")).not.toBe(stopStatusTone("none"));
  });
});

describe("缺失数据的标记", () => {
  it("名义与保证金不完整时带 ≥", () => {
    expect(notionalPrefix("exact")).toBe("");
    expect(notionalPrefix("partial")).toBe("≥");
    expect(marginUsageFloorPrefix(false)).toBe("");
    expect(marginUsageFloorPrefix(true)).toBe("≥");
    expect(marginUsageFloorPrefix(undefined)).toBe("≥");
  });

  it("曲线不可用时给出快照起始时间", () => {
    expect(curveUnavailableText(null)).toContain("尚未开始记录");
    expect(curveUnavailableText("2026-11-15T00:00:00Z")).toContain("快照自");
  });
});

describe("订单文案", () => {
  it("买卖与状态都有中文", () => {
    expect(orderSideLabel("buy")).toBe("买入");
    expect(orderSideLabel("sell")).toBe("卖出");
    expect(orderStatusLabel("filled")).toBe("已成交");
    expect(orderStatusLabel("live")).toBe("挂单中");
  });

  it("未知状态原样显示，不猜", () => {
    expect(orderStatusLabel("some_new_state")).toBe("some_new_state");
  });
});

const STREAM_POSITION = {
  pos_id: "pos-1",
  inst_id: "AAPL-USDT-SWAP",
  display_symbol: "AAPL-USDT",
  name: "Apple",
  asset_class: "equity_perp",
  pos_side: "long",
  size: "8",
  avg_px: "226.80",
  mark_px: "231.42",
  upl: "36.96",
  upl_ratio: "0.0204",
  lever: "3",
  mgn_mode: "isolated",
  liq_px: null,
  margin: "0",
  as_of: "2026-11-14T10:05:00Z",
  received_at: "2026-11-14T10:05:01Z",
};

describe("卡片推送合并", () => {
  const CARDS: PositionCards = {
    as_of: "2026-11-14T10:00:00Z",
    status: "ok",
    items: [
      {
        pos_id: "pos-1",
        inst_id: "AAPL-USDT-SWAP",
        display_symbol: "AAPL-USDT",
        name: "Apple",
        asset_class: "equity_perp",
        pos_side: "long",
        size: "8",
        avg_px: "226.80",
        mark_px: "231.42",
        upl: "36.96",
        upl_ratio: "0.0204",
        lever: "3",
        mgn_mode: "isolated",
        liq_px: null,
        margin: "0",
        notional: "1851.36",
        weight_pct: "79.1",
        stop_status: "confirmed",
        stop_px: "220",
        stop_distance_pct: "4.93",
        upl_curve: [],
      },
    ],
  };

  it("推送只覆盖价格与盈亏，止损与曲线保持 HTTP 快照", () => {
    const merged = mergeCardUpdates(CARDS, {
      "pos-1": {
        ...STREAM_POSITION,
        mark_px: "240.00",
        upl: "50.00",
        received_at: "2026-11-14T10:05:00Z",
      },
    });

    expect(merged.items[0].mark_px).toBe("240.00");
    expect(merged.items[0].upl).toBe("50.00");
    expect(merged.items[0].stop_status).toBe("confirmed");
    expect(merged.items[0].stop_px).toBe("220");
  });

  it("标记价一变，止损距离随之清空，同卡不留两份矛盾的数", () => {
    const merged = mergeCardUpdates(CARDS, {
      "pos-1": { ...STREAM_POSITION, mark_px: "240.00" },
    });

    expect(merged.items[0].mark_px).toBe("240.00");
    expect(merged.items[0].stop_distance_pct).toBeNull();
    // 止损价位与状态仍然来自 HTTP 快照
    expect(merged.items[0].stop_px).toBe("220");
    expect(merged.items[0].stop_status).toBe("confirmed");
  });

  it("标记价没变时止损距离保留", () => {
    const merged = mergeCardUpdates(CARDS, {
      "pos-1": { ...STREAM_POSITION, mark_px: "231.42", upl: "40.00" },
    });

    expect(merged.items[0].upl).toBe("40.00");
    expect(merged.items[0].stop_distance_pct).toBe("4.93");
  });

  it("早于快照时刻的推送被忽略", () => {
    const stale = {
      "pos-1": {
        ...STREAM_POSITION,
        mark_px: "1.00",
        as_of: "2026-11-14T09:00:00Z",
        received_at: "2026-11-14T09:00:01Z",
      },
    };

    expect(mergeCardUpdates(CARDS, stale)).toBe(CARDS);
  });
});

describe("显示格式", () => {
  it("金额固定两位小数并带千分位：除法产生的小数不会原样露出", () => {
    expect(amountText("413.45")).toBe("413.45");
    expect(amountText("723.6")).toBe("723.60");
    expect(amountText("211.912423333333")).toBe("211.91");
    expect(amountText("1786.3909")).toBe("1,786.39");
    expect(amountText(null)).toBe(MISSING_VALUE);
  });

  it("价格不补零，最多四位小数", () => {
    expect(priceText("276.71")).toBe("276.71");
    expect(priceText("60470")).toBe("60,470");
    expect(priceText("1717.3")).toBe("1,717.3");
  });

  it("百分比只保留一位小数并补 %", () => {
    expect(percentText("51.254667634136")).toBe("51.3%");
    expect(percentText("79.1")).toBe("79.1%");
    expect(percentText("100")).toBe("100%");
    expect(percentText(null)).toBe(MISSING_VALUE);
  });

  it("正负号只加在正数上，0 不加号", () => {
    expect(signedAmountText("15.4")).toBe("+15.40");
    expect(signedAmountText("-2.18")).toBe("-2.18");
    expect(signedAmountText("0")).toBe("0.00");
  });
});
