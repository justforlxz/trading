import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

import { describe, expect, it } from "vitest";

import type { DashboardSummary } from "../../lib/dashboard";
import type { OverviewViewProps } from "../overview/view";
import { OverviewView } from "../overview/view";

function summary(): DashboardSummary {
  return {
    as_of: "2026-11-13T09:00:00Z",
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
          {
            inst_type: "SWAP",
            session: "pre",
            primary_source: "us_equity_proxy",
            bar: "1d",
            as_of: "2026-11-13T09:00:00Z",
            breadth: { advancers: 5, decliners: 5, unchanged: 0, ratio: "1", participants: 10 },
            resonance: { strength: "0", participants: 10, window: 20 },
          },
        ],
      },
    },
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

function render(overrides: Partial<OverviewViewProps> = {}): string {
  return renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(OverviewView, {
        summary: summary(),
        error: null,
        loading: false,
        priceLiveness: "live" as const,
        accountLiveness: "live" as const,
        pushed: { account: null, positions: {}, watchlist: {} },
        onRefresh: () => undefined,
        ...overrides,
      }),
    ),
  );
}

describe("首页 v6", () => {
  it("八个模块都在页面上，重要模块在前", () => {
    const html = render();
    const order = [
      "market",
      "account",
      "risk",
      "positions",
      "market_summary",
      "watchlist",
      "alerts",
      "strategies",
      "activity",
    ];
    let cursor = -1;
    for (const name of order) {
      const index = html.indexOf(`data-module="${name}"`);
      expect(index, `缺少模块：${name}`).toBeGreaterThan(-1);
      expect(index, `模块顺序不符：${name}`).toBeGreaterThan(cursor);
      cursor = index;
    }
  });

  it("数值全部来自后端，不在页面里重算", () => {
    const html = render();
    expect(html).toContain("1248.60 USDT");
    expect(html).toContain("45.36%");
    expect(html).toContain("231.42");
    expect(html).toContain("+1.86%");
    expect(html).toContain("+12.4%");
    expect(html).toContain("6.1%");
    expect(html).toContain("名义价值合计");
    expect(html).toContain("1851.36 USDT");
  });

  it("风险卡把最大实际占比写成敞口，不写成上限", () => {
    const html = render();
    expect(html).toContain("最大单标的敞口");
    expect(html).not.toContain("单标的权重上限");
    expect(html).toContain("100%");
  });

  it("止损距离为空时写后端未返回，不写未设置止损", () => {
    const html = render();
    const positionsStart = html.indexOf('data-module="positions"');
    const positionsEnd = html.indexOf('data-module="watchlist"', positionsStart);
    const section = html.slice(positionsStart, positionsEnd);
    expect(section).toContain("后端未返回止损距离");
    expect(section).not.toContain("未设置止损");

    const base = summary();
    const withStop = render({
      summary: {
        ...base,
        positions: {
          ...base.positions,
          data: {
            ...base.positions.data!,
            items: [{ ...base.positions.data!.items[0], stop_distance_pct: "3.2" }],
          },
        },
      },
    });
    expect(withStop).toContain("距止损 3.2%");
  });

  it("日盈亏基准读契约字段，不写死口径", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        account: {
          ...base.account,
          data: { ...base.account.data!, day_pnl_basis: "equity_only" },
        },
      },
    });
    expect(html).toContain("日盈亏基准：仅账户权益");
    expect(html).not.toContain("现金流水调整");
  });

  it("市场概况卡没有对应页面时不渲染跳转入口", () => {
    const html = render();
    expect(html).not.toContain("打开市场概况所在页面");
  });

  it("单个模块失效只降级自己，其余模块照常渲染", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        account: { status: "unavailable", as_of: null, error: "OKX 读取失败", data: null },
        risk: { status: "stale", as_of: "2026-11-12T09:00:00Z", error: "风险快照过期", data: null },
        market: { status: "unconfigured", as_of: null, error: "未配置 OKX 密钥", data: null },
        degraded: [
          { module: "account", status: "unavailable", reason: "OKX 读取失败" },
          { module: "risk", status: "stale", reason: "风险快照过期" },
          { module: "market", status: "unconfigured", reason: "未配置 OKX 密钥" },
        ],
      },
    });

    expect(html).toContain("不可用（OKX 读取失败）");
    expect(html).toContain("不可用（风险快照过期）");
    expect(html).toContain("不可用（未配置 OKX 密钥）");
    expect(html).toContain("以下模块降级");
    expect(html).toContain("账户概览");
    expect(html).toContain("风险监控");

    // 其余模块仍然给出真实数值。
    expect(html).toContain("+1.86%");
    expect(html).toContain("+12.4%");
    expect(html).toContain("231.42");
  });

  it("模块状态与数据时间逐块标注，降级模块写明确状态", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        watchlist: { status: "stale", as_of: "2026-11-10T16:00:00Z", error: null, data: null },
        degraded: [{ module: "watchlist", status: "stale", reason: "自选快照过期" }],
      },
    });

    expect(html).toContain("陈旧");
    expect(html).toContain("不可用（自选快照过期）");
    expect(html).toContain("数据时间：");
    expect(html).toContain("2026-11-13 17:00");
  });

  it("推送到达后只标注被覆盖的字段，其余字段仍写快照时间", () => {
    const plain = render();
    expect(plain).toContain("HTTP 快照");

    const pushed = render({
      pushed: {
        account: "2026-11-13T09:10:00Z",
        positions: { "exchange:okx-main:123456": "2026-11-13T09:10:00Z" },
        watchlist: { "AAPL-USDT-SWAP": "2026-11-13T09:10:00Z" },
      },
    });
    expect(pushed.match(/1 条记录含推送字段/g)?.length).toBe(3);
    expect(pushed).toContain("价格来自推送 2026-11-13 17:10");
    expect(pushed).toContain("日涨跌、RSI 与趋势仍是 HTTP 快照 2026-11-13 00:00");
    expect(pushed).toContain("标记价与未实现盈亏来自推送 2026-11-13 17:10");
    expect(pushed).toContain("名义价值与止损距离仍是 HTTP 快照 2026-11-13 17:00");
    expect(pushed).toContain("今日盈亏仍为快照");
  });

  it("整页读取失败时只显示原因，不展示任何业务数值", () => {
    const html = render({ summary: null, error: "请求失败（HTTP 502）" });
    expect(html).toContain("请求失败（HTTP 502）");
    expect(html).not.toContain("1248.60");
    expect(html).not.toContain("231.42");
  });

  it("市场摘要没有后端数据时不拼摘要文案", () => {
    const html = render();
    const start = html.indexOf("市场摘要");
    const end = html.indexOf("关注列表", start);
    const section = html.slice(start, end);
    expect(section).toContain("不可用");
    expect(section).toContain("后端尚未提供市场摘要数据");
    expect(section).not.toContain("市场整体偏强");
  });
});
