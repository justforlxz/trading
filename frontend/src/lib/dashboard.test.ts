import { describe, expect, it } from "vitest";

import {
  amountText,
  countText,
  dashboardProblem,
  dataSourceLabel,
  degradedReason,
  exchangePosId,
  exchangeStatusLabel,
  marketSessionLabel,
  moduleStatusView,
  dayPnlBasisLabel,
  percentOrMissingText,
  ratioPercentText,
  signedRatioPercentText,
  withStreamUpdates,
  type DashboardSummary,
} from "./dashboard";

function summary(): DashboardSummary {
  return {
    as_of: "2026-11-13T09:00:00Z",
    account: {
      status: "ok",
      as_of: "2026-11-13T09:00:00Z",
      error: null,
      data: {
        account_id: "okx-main",
        currency: "USDT",
        equity: "1248.60",
        available_equity: "682.30",
        cash_balance: "0",
        unrealized_pnl: "31.84",
        used_margin: "566.30",
        available_margin: "682.30",
        margin_usage_pct: "45.36",
        day_pnl: null,
        day_pnl_basis: "equity_only",
        captured_at: "2026-11-13T09:00:00Z",
        source: "okx_rest",
      },
    },
    risk: {
      status: "ok",
      as_of: "2026-11-13T09:00:00Z",
      error: null,
      data: {
        risk_level: "medium",
        currency: "USDT",
        long_notional: "1851.36",
        short_notional: "0",
        net_notional: "1851.36",
        gross_notional: "1851.36",
        margin_usage_pct: "45.36",
        margin_usage_basis: "margin_ratio",
        position_count: 1,
        near_stop_count: 0,
        high_leverage_count: 0,
        missing_stop_count: 1,
        max_single_instrument_weight_pct: "100",
      },
    },
    positions: {
      status: "ok",
      as_of: "2026-11-13T09:00:00Z",
      error: null,
      data: {
        total: 1,
        exchange_count: 1,
        manual_count: 0,
        exchange_status: "ok",
        items: [
          {
            position_ref: "exchange:okx-main:123456",
            source: "exchange",
            inst_id: "AAPL-USDT-SWAP",
            display_symbol: "AAPL-USDT",
            side: "long",
            leverage: "3",
            mark_price: "231.42",
            notional: "1851.36",
            stop_distance_pct: null,
            unrealized_pnl: "36.96",
          },
          {
            position_ref: "manual:abc",
            source: "manual",
            inst_id: "BTC-USDT",
            display_symbol: "BTC-USDT",
            side: "long",
            leverage: null,
            mark_price: "64880",
            notional: "648.80",
            stop_distance_pct: "3.2",
            unrealized_pnl: "12.00",
          },
        ],
      },
    },
    market: {
      status: "ok",
      as_of: "2026-11-13T09:00:00Z",
      error: null,
      data: {
        session: "pre",
        items: [
          {
            inst_type: "SPOT",
            session: "regular",
            primary_source: "okx_spot",
            bar: "1d",
            as_of: "2026-11-13T09:00:00Z",
            breadth: { advancers: 8, decliners: 2, unchanged: 1, ratio: "4", participants: 11 },
            resonance: { strength: "0.62", participants: 11, window: 20 },
          },
        ],
      },
    },
    watchlist: {
      status: "ok",
      as_of: "2026-11-12T16:00:00Z",
      error: null,
      data: {
        summary: { total: 1, bullish: 1, bearish: 0, coverage_pct: "100" },
        items: [
          {
            inst_id: "AAPL-USDT-SWAP",
            display_symbol: "AAPL",
            name: "Apple",
            last_price: "231.42",
            change_pct_24h: "1.86",
            trend: "bullish",
            rsi_14: "61.4",
            data_status: "ok",
          },
        ],
      },
    },
    alerts: { status: "ok", as_of: null, error: null, data: [] },
    strategies: {
      status: "ok",
      as_of: "2026-11-13T09:00:00Z",
      error: null,
      data: {
        total: 2,
        enabled: 1,
        running: 0,
        pending_signals: null,
        recent_backtest: {
          run_id: "bt_0001",
          data_source: "okx_swap",
          window_days: 30,
          total_return: "0.124",
          max_drawdown: "0.061",
          trade_count: 18,
          as_of: "2026-11-12T10:00:00Z",
        },
      },
    },
    activity: { status: "ok", as_of: "2026-11-13T09:00:00Z", error: null, data: [] },
    degraded: [],
  };
}

describe("首页汇总的结构校验", () => {
  it("缺模块或 degraded 时拒绝渲染，不把残缺响应当成部分正常", () => {
    expect(dashboardProblem(null)).toContain("未返回");
    expect(dashboardProblem({ account: {} })).toContain("缺少模块");
    const missingDegraded = { ...summary() } as Record<string, unknown>;
    delete missingDegraded.degraded;
    expect(dashboardProblem(missingDegraded)).toContain("degraded");
    expect(dashboardProblem(summary())).toBeNull();
  });
});

describe("模块状态与降级原因", () => {
  it("状态文案只认后端四种取值，未知值明确写出", () => {
    expect(moduleStatusView("ok").label).toBe("正常");
    expect(moduleStatusView("ok").ok).toBe(true);
    expect(moduleStatusView("stale").label).toBe("陈旧");
    expect(moduleStatusView("unavailable").label).toBe("不可用");
    expect(moduleStatusView("unconfigured").label).toBe("未配置");
    expect(moduleStatusView("degraded").label).toBe("未知状态");
  });

  it("原因优先用模块自己的 error，其次用顶层 degraded", () => {
    const base = summary();
    expect(
      degradedReason(base, "account", { status: "unavailable", error: "OKX 读取超时" }),
    ).toBe("OKX 读取超时");

    const listed: DashboardSummary = {
      ...base,
      account: { ...base.account, error: null },
      degraded: [
        { module: "account", status: "unavailable", reason: "账户快照不可用" },
      ],
    };
    expect(degradedReason(listed, "account", listed.account)).toBe("账户快照不可用");

    const silent: DashboardSummary = { ...base, account: { ...base.account, error: " " } };
    expect(degradedReason(silent, "account", silent.account)).toBe("模块不可用");
  });
});

describe("枚举与数值文案", () => {
  it("市场时段、行情来源和 OKX 同步状态都给出中文标签", () => {
    expect(marketSessionLabel("pre")).toBe("盘前");
    expect(marketSessionLabel("regular")).toBe("正常交易");
    expect(marketSessionLabel("post")).toBe("盘后");
    expect(marketSessionLabel("closed")).toBe("休市");
    expect(marketSessionLabel("overnight")).toContain("未知时段");

    expect(dataSourceLabel("okx_spot")).toBe("OKX 现货");
    expect(dataSourceLabel("us_equity_proxy")).toBe("美股代理行情");
    expect(dataSourceLabel("nasdaq")).toContain("未知来源");

    expect(exchangeStatusLabel("ok")).toBe("正常");
    expect(exchangeStatusLabel("stale")).toBe("陈旧");
    expect(exchangeStatusLabel("unconfigured")).toBe("未配置");
  });

  it("比率换算成百分比，缺失写未提供，不补 0", () => {
    expect(signedRatioPercentText("0.124")).toBe("+12.4%");
    expect(signedRatioPercentText("-0.031")).toBe("-3.1%");
    expect(ratioPercentText("0.061")).toBe("6.1%");
    expect(signedRatioPercentText(null)).toBe("未提供");
    expect(percentOrMissingText("45.36")).toBe("45.36%");
    expect(percentOrMissingText(undefined)).toBe("未提供");
    expect(percentOrMissingText("  ")).toBe("未提供");
    expect(percentOrMissingText("5.970149253731")).toBe("5.97%");
    expect(percentOrMissingText("100")).toBe("100%");
    expect(percentOrMissingText("abc")).toBe("abc%");
    expect(dayPnlBasisLabel("equity_only")).toBe("仅账户权益");
    expect(dayPnlBasisLabel(undefined)).toBe("未提供");
    expect(dayPnlBasisLabel("cash_flow_adjusted")).toBe("未知基准（cash_flow_adjusted）");
    expect(countText(0)).toBe("0");
    expect(countText(null)).toBe("未提供");
    expect(amountText("1248.60", "USDT")).toBe("1248.60 USDT");
    expect(amountText(null, "USDT")).toBe("未提供");
    expect(amountText("1", null)).toContain("币种");
  });

  it("持仓引用只在 exchange:account:pos_id 形状下取出 pos_id", () => {
    expect(exchangePosId("exchange:okx-main:123456")).toBe("123456");
    expect(exchangePosId("manual:abc")).toBeNull();
    expect(exchangePosId("exchange::123")).toBeNull();
    expect(exchangePosId("exchange:a:b:c")).toBeNull();
  });
});

describe("推送值合并", () => {
  it("没有推送时返回原对象，页面据此标注 HTTP 快照", () => {
    const base = summary();
    const result = withStreamUpdates(base, { quotes: {}, positions: {}, account: null });
    expect(result.summary).toBe(base);
    expect(result.pushed).toEqual({ account: null, positions: {}, watchlist: {} });
  });

  it("账户、持仓与关注价格按推送更新，其余字段保留 HTTP 值", () => {
    const base = summary();
    const result = withStreamUpdates(base, {
      quotes: {
        "AAPL-USDT-SWAP": {
          inst_id: "AAPL-USDT-SWAP",
          last: "233.10",
          mark: null,
          index: null,
          source: "okx",
          stale: false,
          snapshot: false,
          as_of: "2026-11-13T09:10:00Z",
          received_at: "2026-11-13T09:10:01Z",
        },
      },
      positions: {
        "123456": {
          pos_id: "123456",
          inst_id: "AAPL-USDT-SWAP",
          display_symbol: "AAPL-USDT",
          name: "Apple",
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
          as_of: "2026-11-13T09:10:00Z",
          received_at: "2026-11-13T09:10:01Z",
        },
      },
      account: {
        account_id: "okx-main",
        currency: "USDT",
        equity: "1260.00",
        available_equity: "690.00",
        cash_balance: "0",
        unrealized_pnl: "50.40",
        used_margin: "570.00",
        available_margin: "690.00",
        margin_usage_pct: "45.24",
        captured_at: "2026-11-13T09:10:00Z",
        source: "okx_ws",
        as_of: "2026-11-13T09:10:00Z",
        received_at: "2026-11-13T09:10:01Z",
      },
    });

    const merged = result.summary;

    expect(merged.account.data?.equity).toBe("1260.00");
    expect(merged.account.data?.source).toBe("okx_ws");
    expect(merged.account.data?.day_pnl_basis).toBe("equity_only");
    expect(merged.account.data?.day_pnl).toBeNull();

    expect(merged.positions.data?.items[0].mark_price).toBe("233.10");
    expect(merged.positions.data?.items[0].unrealized_pnl).toBe("50.40");
    expect(merged.positions.data?.items[0].notional).toBe("1851.36");
    expect(merged.positions.data?.items[1].mark_price).toBe("64880");

    expect(merged.watchlist.data?.items[0].last_price).toBe("233.10");
    expect(merged.watchlist.data?.items[0].change_pct_24h).toBe("1.86");

    // 模块时间保持 HTTP 快照，不被推送推进。
    expect(merged.account.as_of).toBe(base.account.as_of);
    expect(merged.positions.as_of).toBe(base.positions.as_of);
    expect(merged.watchlist.as_of).toBe(base.watchlist.as_of);

    // 推送只覆盖部分字段，各字段的时刻单独记录。
    expect(result.pushed).toEqual({
      account: "2026-11-13T09:10:00Z",
      positions: { "exchange:okx-main:123456": "2026-11-13T09:10:00Z" },
      watchlist: { "AAPL-USDT-SWAP": "2026-11-13T09:10:00Z" },
    });
  });

  it("价格推送不改写日涨跌与 RSI，模块时间保持快照时刻", () => {
    const base = summary();
    const result = withStreamUpdates(base, {
      quotes: {
        "AAPL-USDT-SWAP": {
          inst_id: "AAPL-USDT-SWAP",
          last: "355.76",
          mark: null,
          index: null,
          source: "okx_ws",
          stale: false,
          snapshot: false,
          as_of: "2026-11-15T07:07:00Z",
          received_at: "2026-11-15T07:07:01Z",
        },
      },
      positions: {},
      account: null,
    });

    const item = result.summary.watchlist.data?.items[0];
    expect(item?.last_price).toBe("355.76");
    // 同一行其余字段仍是 HTTP 快照，不能被价格推送带着一起「变新」。
    expect(item?.change_pct_24h).toBe("1.86");
    expect(item?.rsi_14).toBe("61.4");
    expect(item?.trend).toBe("bullish");
    expect(result.summary.watchlist.as_of).toBe(base.watchlist.as_of);
    expect(result.pushed.watchlist["AAPL-USDT-SWAP"]).toBe("2026-11-15T07:07:00Z");
  });

  it("早于模块时刻的推送不覆盖，避免同步后回退", () => {
    const base = summary();
    const result = withStreamUpdates(base, {
      quotes: {
        "AAPL-USDT-SWAP": {
          inst_id: "AAPL-USDT-SWAP",
          last: "220.00",
          mark: null,
          index: null,
          source: "okx",
          stale: false,
          snapshot: false,
          as_of: "2026-11-11T09:00:00Z",
          received_at: "2026-11-11T09:00:01Z",
        },
      },
      positions: {},
      account: {
        account_id: "okx-main",
        currency: "USDT",
        equity: "1000.00",
        available_equity: null,
        cash_balance: null,
        unrealized_pnl: null,
        used_margin: null,
        available_margin: null,
        margin_usage_pct: null,
        captured_at: "2026-11-11T09:00:00Z",
        source: "okx_ws",
        as_of: "2026-11-11T09:00:00Z",
        received_at: "2026-11-11T09:00:01Z",
      },
    });
    expect(result.summary).toBe(base);
    expect(result.pushed).toEqual({ account: null, positions: {}, watchlist: {} });
  });

  it("降级模块不接收推送值", () => {
    const base: DashboardSummary = {
      ...summary(),
      account: { status: "unavailable", as_of: null, error: "账户不可用", data: null },
    };
    const result = withStreamUpdates(base, {
      quotes: {},
      positions: {},
      account: {
        account_id: "okx-main",
        currency: "USDT",
        equity: "1260.00",
        available_equity: null,
        cash_balance: null,
        unrealized_pnl: null,
        used_margin: null,
        available_margin: null,
        margin_usage_pct: null,
        captured_at: "2026-11-13T09:10:00Z",
        source: "okx_ws",
        as_of: "2026-11-13T09:10:00Z",
        received_at: "2026-11-13T09:10:01Z",
      },
    });
    expect(result.summary.account).toBe(base.account);
    expect(result.pushed.account).toBeNull();
  });
});
