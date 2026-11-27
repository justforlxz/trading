import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import type { AccountSummary, EquityCurve, PositionCard } from "../../lib/positions";
import { AssetCardView } from "../positions/asset-card";
import { HitStripView } from "../positions/hit-strip";
import {
  ORDER_HISTORY_ERROR_TEXT,
  OrderHistoryBody,
} from "../positions/order-history-dialog";
import { PositionCardView } from "../positions/position-card";
import type { RiskExposure } from "../../lib/risk";

const ACCOUNT: AccountSummary = {
  account_id: "okx-main",
  currency: "USDT",
  equity: "413.45",
  available_equity: "110.94",
  unrealized_pnl: "0",
  used_margin: "0",
  available_margin: "0",
  margin_usage_pct: "50.8",
  day_pnl_basis: "equity_only",
  position_notional: "723.60",
  gross_notional: "723.60",
  net_notional: "723.60",
  notional_status: "exact",
  margin_used: "209.86",
  margin_usage_floor: false,
  status: "ok",
};

function curve(overrides: Partial<EquityCurve> = {}): EquityCurve {
  return {
    range: "1d",
    available: true,
    points: [
      { at: "2026-11-25T00:00:00Z", value: "404.00" },
      { at: "2026-11-25T12:00:00Z", value: "413.45" },
    ],
    first_snapshot_at: "2026-11-15T00:00:00Z",
    last_snapshot_at: "2026-11-25T12:00:00Z",
    ...overrides,
  };
}

function card(overrides: Partial<PositionCard> = {}): PositionCard {
  return {
    pos_id: "pos-1",
    inst_id: "AAPL-USDT-SWAP",
    display_symbol: "AAPL-USDT",
    name: "Apple",
    asset_class: "equity_perp",
    inst_type: "SWAP",
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
    cost: "604.80",
    stop_supported: true,
    stop_status: "confirmed",
    stop_px: "220",
    stop_distance_pct: "4.93",
    upl_curve: [
      { at: "2026-11-25T00:00:00Z", value: "20" },
      { at: "2026-11-25T12:00:00Z", value: "36.96" },
    ],
    ...overrides,
  };
}

function renderAsset(overrides: { curve?: EquityCurve | null } = {}) {
  return renderToStaticMarkup(
    createElement(AssetCardView, {
      account: ACCOUNT,
      curve: overrides.curve === undefined ? curve() : overrides.curve,
      range: "1d",
      onRangeChange: () => {},
      loading: false,
    }),
  );
}

describe("资产卡", () => {
  it("有数据时画折线，并展示权益与次级指标", () => {
    const html = renderAsset();

    expect(html).toContain("账户权益（OKX totalEq）");
    expect(html).toContain("413.45");
    expect(html).toContain("<polyline");
    expect(html).toContain("110.94");
    expect(html).toContain("723.60");
    expect(html).toContain("209.86");
    expect(html).toContain("50.8%");
  });

  it("一个月没有数据时不画任何折线，并说明快照起始时间", () => {
    const html = renderAsset({
      curve: curve({ range: "1m", available: false, points: [] }),
    });

    expect(html).not.toContain("polyline");
    expect(html).toContain("这段区间还没有数据");
    expect(html).toContain("快照自");
  });

  it("曲线尚未加载完时也不画线", () => {
    const html = renderAsset({ curve: null });

    expect(html).not.toContain("polyline");
    expect(html).toContain("曲线来自账户快照");
  });

  it("名义合计不完整时数字前标 ≥", () => {
    const html = renderToStaticMarkup(
      createElement(AssetCardView, {
        account: { ...ACCOUNT, notional_status: "partial", margin_usage_floor: true },
        curve: curve(),
        range: "1d",
        onRangeChange: () => {},
        loading: false,
      }),
    );

    expect(html).toContain("≥723.60");
    expect(html).toContain("(≥50.8%)");
  });

  it("五个区间按钮都在，选中态用主色", () => {
    const html = renderAsset();

    for (const label of ["1 天", "1 周", "1 月", "半年", "1 年"]) {
      expect(html).toContain(label);
    }
    expect(html).toContain("bg-primary text-primary-foreground");
  });
});

describe("持仓卡片", () => {
  it("有行情时展示收益、投入、平均买入价、最新价格与止损价位", () => {
    const html = renderToStaticMarkup(
      createElement(PositionCardView, { card: card(), onShowOrders: () => {} }),
    );

    expect(html).toContain("AAPL-USDT");
    expect(html).toContain("+36.96");
    expect(html).toContain("多 · 3x");
    expect(html).toContain("已设止损");
    expect(html).toContain("220");
    // 用户给的清单：投入 / 收益 / 平均买入价 / 最新价格 / 强平价（仅合约）。
    expect(html).toContain("投入");
    expect(html).toContain("604.80");
    expect(html).toContain("平均买入价");
    expect(html).toContain("226.8");
    expect(html).toContain("最新价格");
    expect(html).toContain("231.42");
    expect(html).toContain("强平价");
    expect(html).toContain("查看订单历史");
    // 曲线来自 upl 序列，不是价格
    expect(html).toContain('data-upl-curve=""');
  });

  it("不再展示名义与占比", () => {
    const html = renderToStaticMarkup(
      createElement(PositionCardView, { card: card(), onShowOrders: () => {} }),
    );

    expect(html).not.toContain("名义");
    expect(html).not.toContain("占比");
  });

  it("现货没有强平价这一行", () => {
    const html = renderToStaticMarkup(
      createElement(PositionCardView, {
        card: card({ inst_type: "SPOT", lever: null, liq_px: null, stop_supported: false }),
        onShowOrders: () => {},
      }),
    );

    expect(html).not.toContain("强平价");
  });

  it("没有行情的持仓保留卡片并用骨架占位", () => {
    const html = renderToStaticMarkup(
      createElement(PositionCardView, {
        card: card({ mark_px: null, upl: null, upl_ratio: null }),
        onShowOrders: () => {},
      }),
    );

    expect(html).toContain("data-position-card");
    expect(html).toContain("行情待同步");
    expect(html).toContain("animate-pulse");
    expect(html).not.toContain('data-upl-curve=""');
  });

  it("未取到止损与未挂止损是两种文案", () => {
    const unavailable = renderToStaticMarkup(
      createElement(PositionCardView, {
        card: card({ stop_status: "unavailable", stop_px: null, stop_distance_pct: null }),
        onShowOrders: () => {},
      }),
    );
    const none = renderToStaticMarkup(
      createElement(PositionCardView, {
        card: card({ stop_status: "none", stop_px: null, stop_distance_pct: null }),
        onShowOrders: () => {},
      }),
    );

    expect(unavailable).toContain("未取到");
    expect(unavailable).not.toContain("未挂止损");
    expect(none).toContain("未挂止损");
  });

  it("现货卡片写明没有止损，既不是「未取到」也不是「未挂止损」", () => {
    const html = renderToStaticMarkup(
      createElement(PositionCardView, {
        card: card({
          inst_id: "XAAPL-USDT",
          display_symbol: "AAPL-USDT",
          inst_type: "SPOT",
          lever: null,
          stop_supported: false,
          stop_status: "unavailable",
          stop_px: null,
          stop_distance_pct: null,
        }),
        onShowOrders: () => {},
      }),
    );

    expect(html).toContain("现货无止损");
    expect(html).not.toContain("未取到");
    expect(html).not.toContain("未挂止损");
    // 现货没有杠杆：徽标那一行不出现「· 3x」这类合约字段。
    expect(html).not.toContain("· 3x");
  });

  it("同一标的的现货与永续卡片靠形态标签区分", () => {
    const render = (overrides: Partial<PositionCard>) =>
      renderToStaticMarkup(
        createElement(PositionCardView, { card: card(overrides), onShowOrders: () => {} }),
      );

    const spot = render({ inst_id: "XAAPL-USDT", inst_type: "SPOT", lever: null });
    const swap = render({ inst_id: "AAPL-USDT-SWAP", inst_type: "SWAP" });

    // 产品名相同：现货与永续是同一标的的两种形态，单标的敞口要靠它合并。
    expect(spot).toContain("AAPL-USDT");
    expect(swap).toContain("AAPL-USDT");
    // 形态标签不同，这就是用户分辨「哪张是现货」的依据。
    expect(spot).toContain('data-inst-form="现货"');
    expect(swap).toContain('data-inst-form="永续"');
  });

  it("卡片写出价格的时刻，不让日线收盘价冒充当前价", () => {
    const html = renderToStaticMarkup(
      createElement(PositionCardView, {
        card: card({ mark_px_at: "2026-11-17T07:00:00Z" }),
        onShowOrders: () => {},
      }),
    );

    expect(html).toContain("行情 2026-11-17 15:00");
  });

  it("没有价格时刻时不占位", () => {
    const html = renderToStaticMarkup(
      createElement(PositionCardView, {
        card: card({ mark_px_at: null }),
        onShowOrders: () => {},
      }),
    );

    expect(html).not.toContain("行情 20");
  });

  it("标的还没同步时不猜形态，卡片上不出现形态标签", () => {
    const html = renderToStaticMarkup(
      createElement(PositionCardView, {
        card: card({ inst_type: null }),
        onShowOrders: () => {},
      }),
    );

    expect(html).not.toContain("data-inst-form");
  });
});

function exposure(): RiskExposure {
  return {
    as_of: "2026-11-25T12:00:00Z",
    status: "ok",
    summary: {
      long_notional: "723.60",
      short_notional: "0",
      net_notional: "723.60",
      gross_notional: "723.60",
      margin_usage_pct: "50.8",
      margin_usage_basis: "notional_over_leverage",
      max_single_instrument_weight_pct: "79.1",
      risk_level: "medium",
      currency: "USDT",
    },
    positions: [
      {
        position_ref: "exchange:okx-main:pos-1",
        source: "exchange",
        inst_id: "AAPL-USDT-SWAP",
        display_symbol: "AAPL-USDT",
        side: "long",
        notional: "723.60",
        weight_pct: "79.1",
        mark_px: "231.42",
        stop_px: null,
        stop_status: "none",
        stop_distance_pct: null,
        atr_distance: null,
        lever: "3",
        flags: ["stop_missing"],
      },
    ],
    sectors: [],
    rules: [
      { rule_id: "stop_missing", level: "warning", position_ref: "p1", value: null, threshold: null },
      { rule_id: "stop_missing", level: "warning", position_ref: "p2", value: null, threshold: null },
      { rule_id: "high_leverage", level: "warning", position_ref: "p1", value: "10", threshold: "3" },
      {
        rule_id: "single_instrument_weight",
        level: "warning",
        position_ref: "p1",
        value: "79.1",
        threshold: "30",
      },
    ],
  };
}

describe("风控命中条", () => {
  it("最大单标的占比直接用后端给的值，不自己聚合", () => {
    const html = renderToStaticMarkup(
      createElement(HitStripView, {
        // 持仓上的 weight_pct 故意与 summary 不一致：徽标应当跟 summary 走。
        exposure: {
          ...exposure(),
          summary: { ...exposure().summary, max_single_instrument_weight_pct: "12.5" },
        },
        onOpenSettings: () => {},
      }),
    );

    expect(html).toContain("最大单标的占比 12.5%");
    expect(html).not.toContain("79.1%");
  });

  it("只数命中条数，并给出最大单标的占比", () => {
    const html = renderToStaticMarkup(
      createElement(HitStripView, { exposure: exposure(), onOpenSettings: () => {} }),
    );

    expect(html).toContain("风控命中");
    expect(html).toContain("未挂止损 2");
    expect(html).toContain("杠杆过高 1");
    expect(html).toContain("最大单标的占比 79.1%");
    expect(html).toContain("调整规则");
  });

  it("「没查到止损」单列中性徽标，不混进「未挂止损」", () => {
    const base = exposure();
    const html = renderToStaticMarkup(
      createElement(HitStripView, {
        exposure: {
          ...base,
          positions: base.positions.map((position) => ({
            ...position,
            stop_status: "unavailable" as const,
          })),
          rules: [],
        },
        onOpenSettings: () => {},
      }),
    );

    expect(html).toContain("止损未取到 1");
    expect(html).not.toContain("未挂止损");
  });

  it("没有命中时显示「无」，不隐藏整条", () => {
    const html = renderToStaticMarkup(
      createElement(HitStripView, {
        exposure: { ...exposure(), rules: [] },
        onOpenSettings: () => {},
      }),
    );

    expect(html).toContain("风控命中");
    expect(html).toContain("无");
  });
});

describe("订单历史弹窗的失败态", () => {
  const RAW = "请求 /api/v5/trade/orders-pending?instType=SWAP 失败:[Errno 104] Connection reset by peer";

  it("只显示可读文案与「重试」，原始错误不上屏", () => {
    const html = renderToStaticMarkup(
      createElement(OrderHistoryBody, {
        data: null,
        loading: false,
        error: RAW,
        onRetry: () => {},
      }),
    );

    expect(html).toContain(ORDER_HISTORY_ERROR_TEXT);
    expect(html).toContain("重试");
    // 排障信息没丢：原样放在 title 里
    expect(html).toContain(`title="${RAW}"`);
    // 但可见文本里不能有接口路径、errno 与异常原文
    const visible = html.replace(/title="[^"]*"/g, "");
    expect(visible).not.toContain("Errno");
    expect(visible).not.toContain("Connection reset");
    expect(visible).not.toContain("/api/v5/");
  });

  it("失败态与空态是两种文案：一个能重试，一个只是没有订单", () => {
    const empty = renderToStaticMarkup(
      createElement(OrderHistoryBody, {
        data: { inst_id: "AAPL-USDT-SWAP", scope: "all", window_days: 90, items: [] },
        loading: false,
        error: null,
        onRetry: () => {},
      }),
    );

    expect(empty).toContain("该分类下没有订单");
    expect(empty).not.toContain(ORDER_HISTORY_ERROR_TEXT);
    expect(empty).not.toContain("重试");
  });

  it("加载中不显示失败态", () => {
    const html = renderToStaticMarkup(
      createElement(OrderHistoryBody, {
        data: null,
        loading: true,
        error: null,
        onRetry: () => {},
      }),
    );

    expect(html).toContain("读取中…");
    expect(html).not.toContain(ORDER_HISTORY_ERROR_TEXT);
  });
});
