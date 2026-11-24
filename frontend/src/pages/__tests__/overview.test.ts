import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

import { describe, expect, it } from "vitest";

import type { MacroOverviewResponse } from "../../lib/api";
import type { DashboardSummary } from "../../lib/dashboard";
import type { PinnedCandidate } from "../../lib/home-pinned";
import type { AiSummary, MarketSnapshot } from "../../lib/market";
import type { HomeViewProps } from "../overview/home";
import { HomeView } from "../overview/home";

/** 六区块 + 结论条顺序，与布局契约一致。 */
const BLOCKS = [
  "conclusion",
  "account",
  "watchlist",
  "positions",
  "market",
  "alerts",
  "system",
] as const;

const SUMMARY_ITEMS = [
  {
    inst_id: "AAPL-USDT-SWAP",
    display_symbol: "AAPL",
    name: "Apple",
    last_price: "231.42",
    change_pct_24h: "1.86",
    trend: "bullish" as const,
    rsi_14: "61.4",
    data_status: "ok" as const,
  },
];

const SUMMARY_POSITIONS = [
  {
    position_ref: "exchange:okx-main:123456",
    source: "exchange" as const,
    inst_id: "AAPL-USDT-SWAP",
    display_symbol: "AAPL-USDT",
    side: "long" as const,
    leverage: "3",
    mark_price: "231.42",
    notional: "1851.36",
    stop_distance_pct: null,
    unrealized_pnl: "36.96",
  },
];

function summary(): DashboardSummary {
  return {
    market: { status: "ok", as_of: null, error: null, data: null },
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
        items: SUMMARY_POSITIONS,
      },
    },
    watchlist: {
      status: "ok",
      as_of: "2026-11-12T16:00:00Z",
      error: null,
      data: {
        summary: { total: 1, bullish: 1, bearish: 0, coverage_pct: "100" },
        items: SUMMARY_ITEMS,
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
        recent_backtest: null,
      },
    },
    activity: { status: "ok", as_of: null, error: null, data: [] },
    degraded: [],
  } as DashboardSummary;
}

function candidates(): PinnedCandidate[] {
  return [
    {
      inst_id: "AAPL-USDT-SWAP",
      display_symbol: "AAPL",
      name: "AAPL",
      detail: "默认",
      last_price: "231.42",
      change_pct_24h: "1.86",
      rsi_14: "61.4",
      trend: "bullish",
    },
  ];
}

function marketOverview(): MarketSnapshot {
  return {
    as_of: "2026-11-15T06:10:00Z",
    stale: false,
    stale_reason: null,
    items: [
      {
        symbol: "BTC",
        name: "Bitcoin",
        value: "100000",
        change: "1200",
        change_pct: "1.01",
        market_session: "regular",
        source: "okx_spot",
        as_of: "2026-11-15T06:00:00Z",
        is_delayed: false,
        quality_status: "normal",
        source_url: "https://www.okx.com/trade-spot/btc-usdt",
      },
    ],
  };
}

function macroOverview(): MacroOverviewResponse {
  return {
    as_of: "2026-11-15T06:10:00Z",
    stale: false,
    stale_reason: null,
    readings: [
      {
        series_id: "us10y",
        name: "美国 10 年期国债",
        unit: "%",
        granularity: "daily",
        provider: "treasury",
        source_url: null,
        value: "4.92",
        change: "-0.12",
        as_of: "2026-11-14T21:00:00Z",
        is_delayed: false,
        market_session: "closed",
        quality_status: "normal",
        regime: null,
        error: null,
      },
    ],
    spread: {
      available: true,
      value_bp: "29",
      inverted: false,
      trading_day: "2026-11-14",
      quality_status: "normal",
      reason: null,
      sources: [{ provider: "treasury", source_url: null }],
    },
  } as MacroOverviewResponse;
}

function aiSummary(): AiSummary {
  return {
    generated_at: "2026-11-15T06:10:00Z",
    overall: "偏强，波动率抬升",
    points: [],
    risks: [],
    disclaimer: "仅作信息归纳，不构成交易建议",
    stale: false,
    stale_notice: null,
  };
}

function render(overrides: Partial<HomeViewProps> = {}): string {
  return renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(HomeView, {
        summary: summary(),
        error: null,
        loading: false,
        priceLiveness: "live" as const,
        accountLiveness: "live" as const,
        pushed: { account: null, positions: {}, watchlist: {} },
        marketOverview: marketOverview(),
        marketOverviewError: null,
        marketOverviewLoading: false,
        macroOverview: macroOverview(),
        macroOverviewError: null,
        macroOverviewLoading: false,
        aiSummary: aiSummary(),
        aiSummaryError: null,
        aiSummaryLoading: false,
        onRefresh: () => undefined,
        pinnedWatchlist: ["AAPL-USDT-SWAP"],
        watchlistCandidates: candidates(),
        onSavePinned: async () => undefined,
        ...overrides,
      }),
    ),
  );
}

/** 结论条的事实段（不含右侧的持仓/同步状态）。 */
function factsOf(html: string): string {
  const matched = html.match(/data-conclusion-facts[^>]*>([\s\S]*?)<\/span>/);
  return matched?.[1] ?? "";
}

/** 取某个区块 `<section>` 上的 class 列表。 */
function blockClass(html: string, block: string): string {
  const matched = html.match(new RegExp(`id="${block}"[^>]*class="([^"]*)"`));
  return matched?.[1] ?? "";
}

/** 表格行里的标识顺序，用来断言排序结果。 */
function rowIds(html: string, attribute: "inst-id" | "position-ref"): string[] {
  return [...html.matchAll(new RegExp(`data-${attribute}="([^"]+)"`, "g"))].map(
    (matched) => matched[1],
  );
}

function sectionOf(html: string, block: string): string {
  const start = html.indexOf(`data-block="${block}"`);
  const next = html.indexOf("data-block=", start + 10);
  return html.slice(start, next === -1 ? html.length : next);
}

describe("首页决策优先布局：区块与分栏", () => {
  it("区块顺序为 结论条 → 资金与风险 → 关注列表 → 当前持仓 → 市场环境 → 提醒 → 系统状态", () => {
    const html = render();
    let cursor = -1;
    for (const block of BLOCKS) {
      const index = html.indexOf(`data-block="${block}"`);
      expect(index, `缺少区块：${block}`).toBeGreaterThan(-1);
      expect(index, `区块顺序不符：${block}`).toBeGreaterThan(cursor);
      cursor = index;
    }
  });

  it("lg 断点按 12 栏 5/7、7/5、7/5 分栏，结论条通栏", () => {
    const html = render();
    expect(html).toContain("grid gap-4 lg:grid-cols-12");
    expect(blockClass(html, "conclusion")).toContain("lg:col-span-12");
    expect(blockClass(html, "account")).toContain("lg:col-span-5");
    expect(blockClass(html, "watchlist")).toContain("lg:col-span-7");
    expect(blockClass(html, "positions")).toContain("lg:col-span-7");
    expect(blockClass(html, "market")).toContain("lg:col-span-5");
    expect(blockClass(html, "alerts")).toContain("lg:col-span-7");
    expect(blockClass(html, "system")).toContain("lg:col-span-5");
  });

  it("窄屏单列：所有 col-span 类都带 lg: 前缀，基础栅格不分栏", () => {
    const html = render();
    const gridClass = html.match(/class="([^"]*lg:grid-cols-12[^"]*)"/)?.[1] ?? "";
    expect(gridClass).toContain("grid");
    expect(gridClass).not.toMatch(/(?:^| )grid-cols-\d/);

    for (const block of BLOCKS.slice(1)) {
      const spans = blockClass(html, block)
        .split(" ")
        .filter((name) => name.includes("col-span"));
      expect(spans.length, `${block} 没有分栏类`).toBeGreaterThan(0);
      for (const span of spans) {
        expect(span.startsWith("lg:"), `${block} 的分栏 ${span} 必须在 lg 断点下生效`).toBe(true);
      }
    }
  });
});

describe("首页结论条只用后端字段", () => {
  it("四项齐全时拼成一句话，并给出建议动作", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        account: {
          ...base.account,
          data: { ...base.account.data!, margin_usage_pct: "32" },
        },
        risk: {
          ...base.risk,
          data: {
            ...base.risk.data!,
            missing_stop_count: 4,
            high_leverage_count: 1,
          },
        },
        watchlist: {
          ...base.watchlist,
          data: {
            ...base.watchlist.data!,
            summary: { total: 7, bullish: 2, bearish: 5, coverage_pct: "100" },
          },
        },
      },
    });

    expect(factsOf(html)).toBe("保证金 32% · 缺止损 4 个 · 高杠杆 1 个 · 自选 5/7 走弱");
    expect(html).toContain("先处理止损");
  });

  it("高杠杆为 0 时整项省略，不做页面侧判断", () => {
    expect(factsOf(render())).toBe("保证金 45% · 缺止损 1 个 · 自选 0/1 走弱");
  });

  it("account 置空时保证金一项消失，且不出现 NaN / undefined", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        account: { status: "unavailable", as_of: null, error: null, data: null },
      },
    });

    expect(factsOf(html)).not.toContain("保证金");
    expect(factsOf(html)).toContain("缺止损 1 个");
    expect(html).not.toContain("NaN");
    expect(html).not.toContain("undefined");
  });

  it("保证金比例缺失时同样整项省略，不写 0%", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        account: { ...base.account, data: { ...base.account.data!, margin_usage_pct: null } },
      },
    });

    expect(factsOf(html)).not.toContain("保证金");
    expect(html).not.toContain("NaN");
    expect(html).toContain("未提供");
  });

  it("风险模块不可用时不给建议动作，避免凭空写「结构正常」", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        risk: { status: "unavailable", as_of: null, error: null, data: null },
      },
    });

    expect(factsOf(html)).not.toContain("缺止损");
    expect(html).not.toContain("结构正常");
    expect(html).not.toContain("先处理止损");
  });
});

describe("首页排序", () => {
  it("自选按涨跌幅绝对值降序，第一行是绝对值最大的标的", () => {
    const base = summary();
    const rows = [
      { instId: "AAA", change: "1.00" },
      { instId: "BBB", change: "-9.00" },
      { instId: "CCC", change: "3.00" },
    ];
    const html = render({
      summary: {
        ...base,
        watchlist: {
          ...base.watchlist,
          data: {
            summary: { total: 3, bullish: 1, bearish: 2, coverage_pct: "100" },
            items: rows.map((row) => ({
              inst_id: row.instId,
              display_symbol: row.instId,
              name: row.instId,
              last_price: "100",
              change_pct_24h: row.change,
              trend: "neutral" as const,
              rsi_14: "50",
              data_status: "ok" as const,
            })),
          },
        },
      },
      pinnedWatchlist: rows.map((row) => row.instId),
      watchlistCandidates: rows.map((row) => ({
        inst_id: row.instId,
        display_symbol: row.instId,
        name: row.instId,
        detail: "默认",
        last_price: "100",
        change_pct_24h: row.change,
        rsi_14: "50",
        trend: "neutral" as const,
      })),
    });

    expect(rowIds(sectionOf(html, "watchlist"), "inst-id")).toEqual(["BBB", "CCC", "AAA"]);
  });

  it("持仓按盈亏绝对值降序，第一行是绝对值最大的持仓", () => {
    const base = summary();
    const rows = [
      { ref: "pos:small", pnl: "10.00" },
      { ref: "pos:biggest", pnl: "-500.00" },
      { ref: "pos:middle", pnl: "200.00" },
    ];
    const html = render({
      summary: {
        ...base,
        positions: {
          ...base.positions,
          data: {
            ...base.positions.data!,
            total: rows.length,
            items: rows.map((row) => ({
              position_ref: row.ref,
              source: "exchange" as const,
              inst_id: `${row.ref}-USDT-SWAP`,
              display_symbol: row.ref,
              side: "long" as const,
              leverage: "2",
              mark_price: "100",
              notional: "1000",
              stop_distance_pct: null,
              unrealized_pnl: row.pnl,
            })),
          },
        },
      },
    });

    expect(rowIds(sectionOf(html, "positions"), "position-ref")).toEqual([
      "pos:biggest",
      "pos:middle",
      "pos:small",
    ]);
  });
});

describe("首页空状态与降级", () => {
  it("没有置顶标的时给出选择入口，不把整份自选铺开", () => {
    const section = sectionOf(render({ pinnedWatchlist: [] }), "watchlist");
    expect(section).toContain("已选 0/5");
    expect(section).toContain("还没有置顶标的");
    expect(section).toContain("编辑");
    expect(rowIds(section, "inst-id")).toEqual([]);
  });

  it("没有持仓、提醒、活动时各自给出空状态", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        positions: {
          ...base.positions,
          data: { ...base.positions.data!, total: 0, items: [] },
        },
      },
    });

    expect(sectionOf(html, "positions")).toContain("没有持仓");
    expect(sectionOf(html, "alerts")).toContain("没有待处理的提醒");
  });

  it("单模块降级时整页给出降级提示，其余区块照常渲染", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        account: { status: "unavailable", as_of: null, error: "OKX 读取失败", data: null },
        degraded: [
          { module: "account", status: "unavailable", reason: "OKX 读取失败" },
        ] as DashboardSummary["degraded"],
      },
    });

    expect(html).toContain("以下模块降级");
    expect(html).toContain("账户概览（OKX 读取失败）");
    expect(sectionOf(html, "account")).toContain("账户数据不可用");
    expect(html).toContain("231.42");
  });

  it("行情读取失败时只在市场环境里报错，不显示旧值", () => {
    const html = render({
      marketOverview: null,
      marketOverviewError: "OKX BTC 行情读取失败（HTTP 502）",
    });

    const section = sectionOf(html, "market");
    expect(section).toContain("OKX BTC 行情读取失败（HTTP 502）");
    expect(section).not.toContain("100000");
  });

  it("推送断开时给出提示，不把最后已知值当成实时值", () => {
    const html = render({ priceLiveness: "stale" as const });
    expect(html).toContain("实时推送已断开：关注列表价格为最后已知值");
  });
});
describe("缺失数据不写成确定结论", () => {
  it("风险模块不可用时两个计数徽标写「未提供」并用中性配色，不写 0", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        risk: { status: "unavailable", as_of: null, error: null, data: null },
      },
    });
    const section = sectionOf(html, "account");

    expect(section).not.toContain("缺止损 0");
    expect(section).not.toContain("高杠杆 0");
    expect(section).toContain("缺止损 未提供");
    expect(section).toContain("高杠杆 未提供");

    // 还能用告警色的话，读者仍会把它当成「有风险的 0 个」，所以要退回中性配色。
    for (const label of ["缺止损 未提供", "高杠杆 未提供"]) {
      const badge = section.match(
        new RegExp(`<span class="([^"]*)"[^>]*>\\s*${label}\\s*</span>`),
      );
      expect(badge, `找不到「${label}」徽标`).not.toBeNull();
      expect(badge![1]).not.toContain("rose");
      expect(badge![1]).not.toContain("amber");
    }
  });

  it("持仓模块不可用时结论条不写同步状态，系统状态省掉这一行", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        positions: { status: "unavailable", as_of: null, error: null, data: null },
      },
    });

    expect(html).not.toContain("同步异常");
    expect(html).not.toContain("同步正常");
    expect(sectionOf(html, "system")).not.toContain("持仓同步");
  });

  it("持仓同步状态三档都写成中文，不打印后端枚举", () => {
    const cases = [
      ["ok", "正常"],
      ["stale", "陈旧"],
      ["unconfigured", "未配置"],
    ] as const;

    for (const [status, label] of cases) {
      const base = summary();
      const html = render({
        summary: {
          ...base,
          positions: {
            ...base.positions,
            data: { ...base.positions.data!, exchange_status: status },
          },
        },
      });
      const system = sectionOf(html, "system");

      expect(system, `同步状态 ${status} 应写成「${label}」`).toContain(label);
      expect(system, `系统状态栏不应出现原始枚举 ${status}`).not.toMatch(
        /\bok\b|\bstale\b|\bunconfigured\b/,
      );
    }
  });
});
describe("模块不可用时不写空状态", () => {
  /** 把某个模块换成 `data: null` 的不可用信封。 */
  function unavailable(module: "positions" | "alerts" | "watchlist", reason: string) {
    const base = summary();
    return {
      ...base,
      [module]: { status: "unavailable", as_of: null, error: reason, data: null },
      degraded: [
        ...base.degraded,
        { module, status: "unavailable", reason },
      ] as DashboardSummary["degraded"],
    } as DashboardSummary;
  }

  it("持仓模块不可用时不写「没有持仓」，改为写数据不可用", () => {
    const html = render({ summary: unavailable("positions", "持仓快照缺失") });
    const section = sectionOf(html, "positions");

    expect(section).not.toContain("没有持仓");
    expect(section).toContain("持仓数据不可用");
    // 同屏的降级提示要说清是哪一块出了问题。
    expect(html).toContain("当前持仓（持仓快照缺失）");
  });

  it("提醒模块不可用时不写「没有待处理的提醒」，改为写数据不可用", () => {
    const html = render({ summary: unavailable("alerts", "提醒服务未响应") });
    const section = sectionOf(html, "alerts");

    expect(section).not.toContain("没有待处理的提醒");
    expect(section).toContain("提醒数据不可用");
    expect(html).toContain("提醒（提醒服务未响应）");
  });

  it("关注列表模块不可用且没有置顶行时不写「还没有置顶标的」", () => {
    const html = render({
      summary: unavailable("watchlist", "自选快照缺失"),
      pinnedWatchlist: [],
    });
    const section = sectionOf(html, "watchlist");

    expect(section).not.toContain("还没有置顶标的");
    expect(section).toContain("关注列表数据不可用");
  });

  it("模块可用但没有记录时仍然照旧写空状态", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        positions: { ...base.positions, data: { ...base.positions.data!, total: 0, items: [] } },
        alerts: { status: "ok", as_of: null, error: null, data: [] },
      },
      pinnedWatchlist: [],
    });

    expect(sectionOf(html, "positions")).toContain("没有持仓");
    expect(sectionOf(html, "alerts")).toContain("没有待处理的提醒");
    expect(sectionOf(html, "watchlist")).toContain("还没有置顶标的");
  });
});



describe("首页保留既有能力", () => {
  it("关注列表可打开置顶编辑弹窗（最多 5 个）", () => {
    const html = render();
    expect(sectionOf(html, "watchlist")).toContain("编辑");
    expect(html).toContain("已选 1/5");
  });

  it("提醒行有「处理」按钮，携带 acknowledged 状态", () => {
    const base = summary();
    const html = render({
      summary: {
        ...base,
        alerts: {
          status: "ok",
          as_of: "2026-11-13T09:00:00Z",
          error: null,
          data: [
            {
              id: "al_1",
              type: "risk",
              severity: "critical",
              instrument_id: "AAPL-USDT-SWAP",
              rule_id: "stop_distance",
              title: "止损距离过近",
              detail: "AAPL-USDT-SWAP 的止损距离 -9.29，阈值 1",
              status: "pending",
              triggered_at: "2026-11-13T09:00:00Z",
            },
          ],
        } as DashboardSummary["alerts"],
      },
      onResolveAlert: () => undefined,
    });

    const section = sectionOf(html, "alerts");
    expect(section).toContain("止损距离过近");
    expect(section).toContain("处理");
    expect(section).toContain('data-alert-id="al_1"');
  });

  it("推送覆盖只算显示出来的自选行", () => {
    const at = "2026-11-13T09:10:00Z";
    const covered = render({
      pinnedWatchlist: ["AAPL-USDT-SWAP"],
      pushed: { account: null, positions: {}, watchlist: { "AAPL-USDT-SWAP": at } },
    });
    expect(sectionOf(covered, "system")).toContain("1 条自选推送");

    const notCovered = render({
      pinnedWatchlist: ["AAPL-USDT-SWAP"],
      pushed: { account: null, positions: {}, watchlist: { "TSLA-USDT-SWAP": at } },
    });
    expect(sectionOf(notCovered, "system")).toContain("0 条自选推送");
  });

  it("汇总不可用时只写不可用，不展示任何业务数值", () => {
    const html = render({ summary: null, error: "请求失败（HTTP 502）" });
    expect(html).toContain("请求失败（HTTP 502）");
    expect(html).toContain("首页汇总不可用，请重试。");
    expect(html).not.toContain("1248.60");
    expect(html).not.toContain("NaN");
  });
});
