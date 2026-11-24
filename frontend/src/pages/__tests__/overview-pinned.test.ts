import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

import { describe, expect, it } from "vitest";

import type { DashboardSummary } from "../../lib/dashboard";
import type { PinnedCandidate } from "../../lib/home-pinned";
import type { HomeViewProps } from "../overview/home";
import { HomeView } from "../overview/home";
import { WatchlistPicker } from "../overview/watchlist-picker";

const IDS = [
  "BTC-USDT-SWAP",
  "ETH-USDT-SWAP",
  "SOL-USDT-SWAP",
  "AAPL-USDT-SWAP",
  "GOOGL-USDT-SWAP",
  "ASTS-USDT-SWAP",
];

/**
 * 弹窗候选（`GET /api/watchlist` 的快照）。数值刻意与首页汇总不同：卡片要用汇总里更实时的
 * 那一份覆盖，两套数一样就测不出到底取了谁。
 */
function candidates(): PinnedCandidate[] {
  return IDS.map((instId, index) => ({
    inst_id: instId,
    display_symbol: instId.replace(/-USDT-SWAP$/, ""),
    name: instId.replace(/-USDT-SWAP$/, ""),
    detail: index % 2 === 0 ? "默认" : "股票",
    last_price: "7777",
    change_pct_24h: "-77.7",
    rsi_14: "88",
    trend: "bearish" as const,
  }));
}

function watchlistItems() {
  return IDS.slice(0, 5).map((instId, index) => ({
    inst_id: instId,
    display_symbol: instId.replace(/-USDT-SWAP$/, ""),
    name: `标的 ${index + 1}`,
    last_price: `${100 + index}`,
    change_pct_24h: index % 2 === 0 ? "1.5" : "-0.8",
    rsi_14: "50",
    trend: index % 2 === 0 ? ("bullish" as const) : ("bearish" as const),
    data_status: "ok" as const,
  }));
}

function emptyModule(status = "ok") {
  return { status, as_of: "2026-11-23T12:00:00Z", error: null, data: null };
}

function summary(): DashboardSummary {
  const items = watchlistItems();
  return {
    as_of: "2026-11-23T12:00:00Z",
    degraded: [],
    market: emptyModule() as DashboardSummary["market"],
    account: emptyModule() as DashboardSummary["account"],
    risk: emptyModule() as DashboardSummary["risk"],
    positions: emptyModule() as DashboardSummary["positions"],
    watchlist: {
      status: "ok",
      as_of: "2026-11-23T12:00:00Z",
      error: null,
      data: {
        items,
        summary: { total: items.length, bullish: 3, bearish: 2, coverage_pct: "100" },
      },
    } as DashboardSummary["watchlist"],
    alerts: { status: "ok", as_of: null, error: null, data: [] },
    strategies: emptyModule() as DashboardSummary["strategies"],
    activity: { status: "ok", as_of: null, error: null, data: [] },
  };
}

function renderView(overrides: Partial<HomeViewProps> = {}): string {
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
        marketOverview: null,
        marketOverviewError: null,
        marketOverviewLoading: false,
        macroOverview: null,
        macroOverviewError: null,
        macroOverviewLoading: false,
        aiSummary: null,
        aiSummaryError: null,
        aiSummaryLoading: false,
        onRefresh: () => undefined,
        pinnedWatchlist: [],
        watchlistCandidates: candidates(),
        onSavePinned: async () => undefined,
        ...overrides,
      }),
    ),
  );
}

/** 只截关注列表区块：相邻区块的文案不应混进断言。 */
function watchlistSection(html: string): string {
  const start = html.indexOf('data-block="watchlist"');
  const end = html.indexOf('data-block="positions"', start);
  return html.slice(start, end);
}

function systemSection(html: string): string {
  const start = html.indexOf('data-block="system"');
  return html.slice(start);
}

/** 卡片里真的渲染出来的标的，顺序即页面顺序。 */
function cardRows(html: string): string[] {
  return [...watchlistSection(html).matchAll(/data-inst-id="([^"]+)"/g)].map(
    (matched) => matched[1],
  );
}

describe("首页关注列表置顶（卡片）", () => {
  it("只渲染置顶的标的，头部给出已选数量", () => {
    const html = renderView({
      pinnedWatchlist: ["SOL-USDT-SWAP", "BTC-USDT-SWAP", "AAPL-USDT-SWAP"],
    });
    const section = watchlistSection(html);

    expect(section).toContain("已选 3/5");
    expect(cardRows(html).sort()).toEqual(["AAPL-USDT-SWAP", "BTC-USDT-SWAP", "SOL-USDT-SWAP"]);

    // 未置顶的自选标的不出现在卡片里（它们仍在自选页，只是不占首页这一块）。
    for (const instId of ["ETH-USDT-SWAP", "GOOGL-USDT-SWAP", "ASTS-USDT-SWAP"]) {
      expect(section).not.toContain(instId);
    }
  });

  it("没有置顶项时显示空状态与选择入口，不把整份自选铺开", () => {
    const html = renderView({ pinnedWatchlist: [] });
    const section = watchlistSection(html);

    expect(section).toContain("已选 0/5");
    expect(section).toContain("还没有置顶标的");
    expect(section).toContain("编辑");
    expect(cardRows(html)).toEqual([]);
  });

  it("置顶项已从自选删掉时只减这一行，其它置顶项照旧", () => {
    const html = renderView({
      pinnedWatchlist: ["SOL-USDT-SWAP", "GONE-USDT-SWAP", "BTC-USDT-SWAP"],
    });

    expect(watchlistSection(html)).toContain("已选 2/5");
    expect(cardRows(html).sort()).toEqual(["BTC-USDT-SWAP", "SOL-USDT-SWAP"]);
  });
});

describe("首页关注列表置顶（弹窗）", () => {
  function renderPicker(pinned: string[]): string {
    return renderToStaticMarkup(
      createElement(WatchlistPicker, {
        open: true,
        items: candidates(),
        pinned,
        onClose: () => undefined,
        onSave: async () => undefined,
      }),
    );
  }

  /** 按 `<li>…</li>` 取出标的行；返回的片段里带着该行的复选框状态。 */
  function rowOf(html: string, instId: string): string {
    const rows = [...html.matchAll(/<li>([\s\S]*?)<\/li>/g)].map((match) => match[1]);
    const row = rows.find((chunk) => chunk.includes(instId));
    if (row === undefined) throw new Error(`弹窗里没有 ${instId}`);
    return row;
  }

  it("具备 role/aria-modal/aria-labelledby 与标题", () => {
    const html = renderPicker(["BTC-USDT-SWAP"]);

    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toMatch(/aria-labelledby="[^"]+"/);
    expect(html).toContain("编辑首页关注列表");
    expect(html).toContain("从自选里选择，最多 5 个");
  });

  it("已选 5 个时其余项变灰禁用，并提示已选满", () => {
    const html = renderPicker(IDS.slice(0, 5));

    expect(html).toContain("已选 5/5");
    expect(html).toContain("已选满 5 个，取消一个才能再选");
    expect(rowOf(html, IDS[0])).toContain("checked");
    expect(rowOf(html, IDS[5])).toContain("disabled");
    expect(rowOf(html, IDS[5])).not.toContain("checked");
  });

  it("未满 5 个时没有任何项被禁用", () => {
    const html = renderPicker(["BTC-USDT-SWAP"]);

    expect(html).not.toContain("已选满 5 个");
    for (const instId of IDS) {
      expect(rowOf(html, instId)).not.toContain("disabled");
    }
  });

  it("列表覆盖当前全部自选标的", () => {
    const html = renderPicker([]);

    for (const instId of IDS) {
      expect(html).toContain(instId);
    }
  });

  it("候选还没读到时不允许保存，避免把已存的置顶清单清空", () => {
    const html = renderToStaticMarkup(
      createElement(WatchlistPicker, {
        open: true,
        items: [],
        pinned: ["BTC-USDT-SWAP"],
        onClose: () => undefined,
        onSave: async () => undefined,
      }),
    );

    expect(html).toContain("自选中还没有标的");
    expect(html).toMatch(/<button[^>]*disabled[^>]*>保存</);
  });
});

describe("保存后立刻渲染（置顶项落在汇总五行之外）", () => {
  it("候选里有、汇总里没有的置顶项照样出行，不会退回空状态", () => {
    const fixture = summary();
    // 汇总只带前五行，第 6 个标的（ASTS）不在其中，这正是保存后不重新取数就会丢行的那一档。
    const summaryIds = fixture.watchlist.data?.items.map((item) => item.inst_id) ?? [];
    expect(summaryIds).not.toContain("ASTS-USDT-SWAP");

    const html = renderView({ pinnedWatchlist: ["ASTS-USDT-SWAP"] });

    expect(watchlistSection(html)).toContain("已选 1/5");
    expect(watchlistSection(html)).not.toContain("还没有置顶标的");
    expect(cardRows(html)).toEqual(["ASTS-USDT-SWAP"]);
  });

  it("置顶项与汇总有交集时，数值取自汇总（推送写回的那一份）", () => {
    const section = watchlistSection(renderView({ pinnedWatchlist: ["BTC-USDT-SWAP"] }));

    // 汇总夹具：价格 100 + 序号（BTC 是 100）、RSI 50、日涨跌 +1.5%、趋势偏多；
    // 候选夹具一律是 7777 / -77.7% / RSI 88 / 偏空。只认前者才说明覆盖生效。
    expect(section).toContain("BTC");
    expect(section).toContain("100.00");
    expect(section).toContain("+1.50%");
    expect(section).toContain("50");
    expect(section).not.toContain("7777");
    expect(section).not.toContain("-77.70%");
    expect(section).not.toContain("88");
  });
});

describe("推送覆盖只认显示出来的行", () => {
  const at = "2026-11-23T12:05:00Z";

  it("推送只覆盖未置顶的行时，自选推送计数为 0", () => {
    const html = renderView({
      pinnedWatchlist: ["BTC-USDT-SWAP"],
      pushed: { account: null, positions: {}, watchlist: { "TSLA-USDT-SWAP": at } },
    });

    expect(systemSection(html)).toContain("0 条自选推送");
  });

  it("推送覆盖了显示的行时，自选推送计数为 1", () => {
    const html = renderView({
      pinnedWatchlist: ["BTC-USDT-SWAP"],
      pushed: { account: null, positions: {}, watchlist: { "BTC-USDT-SWAP": at } },
    });

    expect(systemSection(html)).toContain("1 条自选推送");
  });
});

describe("保存不会丢掉「已不在自选」的置顶项", () => {
  const GONE = "GONE-USDT-SWAP";

  function renderPickerWithGone(): string {
    return renderToStaticMarkup(
      createElement(WatchlistPicker, {
        open: true,
        items: candidates(),
        pinned: [GONE, "BTC-USDT-SWAP", "AAPL-USDT-SWAP"],
        onClose: () => undefined,
        onSave: async () => undefined,
      }),
    );
  }

  it("已选计数把看不见的置顶项算进去", () => {
    const html = renderPickerWithGone();

    // 草稿是整份已保存清单（3 个），不是「与当前自选求交集」后的 2 个：
    // 否则用户只是打开弹窗点保存，那条不见了自选的置顶项就被永久删除。
    expect(html).toContain("已选 3/5");
  });

  it("把看不见的置顶项单独点名，说明保存后仍会保留", () => {
    const html = renderPickerWithGone();

    expect(html).toContain("已不在自选的置顶项不在这里显示，保存后仍会保留");
    expect(html).toContain("要彻底去掉，先把它加回自选再取消置顶");
    expect(html).toContain(GONE);
    // 它不占列表行：候选里没有它。
    const rows = [...html.matchAll(/<li>([\s\S]*?)<\/li>/g)]
      .map((match) => match[1])
      .filter((chunk) => chunk.includes('type="checkbox"'));
    expect(rows).toHaveLength(IDS.length);
  });

  it("清空置顶后不再有这条提示", () => {
    const html = renderToStaticMarkup(
      createElement(WatchlistPicker, {
        open: true,
        items: candidates(),
        pinned: [],
        onClose: () => undefined,
        onSave: async () => undefined,
      }),
    );

    expect(html).not.toContain("已不在自选的置顶项");
  });
});

describe("幽灵按钮的文字色与原型一致", () => {
  /** 按按钮文字找回对应按钮的 class 列表；整页 HTML 是一行，不能用贪婪/懒惰跨按钮匹配。 */
  function buttonClassOf(html: string, label: string): string | undefined {
    const buttons = [...html.matchAll(/<button[^>]*class="([^"]*)"[^>]*>([\s\S]*?)<\/button>/g)];
    return buttons.find((match) => match[2].includes(label))?.[1];
  }

  it("卡片标题行的「编辑」用 muted-foreground", () => {
    const html = renderView({ pinnedWatchlist: ["BTC-USDT-SWAP"] });
    const classes = buttonClassOf(html, "编辑");

    expect(classes).toBeDefined();
    expect(classes).toContain("text-muted-foreground");
  });

  it("弹窗底部的「取消」用 muted-foreground", () => {
    const html = renderToStaticMarkup(
      createElement(WatchlistPicker, {
        open: true,
        items: candidates(),
        pinned: [],
        onClose: () => undefined,
        onSave: async () => undefined,
      }),
    );
    const classes = buttonClassOf(html, "取消");

    expect(classes).toBeDefined();
    expect(classes).toContain("text-muted-foreground");
  });
});
