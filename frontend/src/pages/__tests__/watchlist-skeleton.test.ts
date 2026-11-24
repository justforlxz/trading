import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { WatchlistItem } from "../../lib/api";
import { watchlistListState, watchlistPanelState } from "../../lib/watchlist";
import { GroupFilter } from "../watchlist/index";
import { WatchlistList } from "../watchlist/list";
import { makeItem } from "./watchlist-fixtures";

/** 把列表渲染成 HTML；`state` 决定画占位行还是真实行。 */
function renderList(
  items: readonly WatchlistItem[],
  options: { state?: "skeleton" | "rows"; loading?: boolean } = {},
): string {
  return renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(WatchlistList, {
        items,
        quotes: {},
        closes: {},
        busy: null,
        groups: ["默认"],
        onRemove: () => {},
        onMove: () => {},
        state: options.state ?? "rows",
        loading: options.loading ?? false,
      }),
    ),
  );
}

function count(html: string, fragment: string): number {
  return html.split(fragment).length - 1;
}

/** 去掉标签只留文字，便于断言按钮上的标签与计数。 */
function plainText(html: string): string {
  return html.replace(/<[^>]*>/g, "");
}

/** 取出表头那一段，用来比对两种状态下的表头是否同一份。 */
function head(html: string): string {
  return html.slice(html.indexOf("<thead>"), html.indexOf("</thead>"));
}

const ITEMS = [
  makeItem("AAPL-USDT-SWAP", { change: "1.86", group: "美股" }),
  makeItem("BTC-USDT-SWAP", { change: "-0.44", group: "加密" }),
];

/** 一组输入对应一种页面状态；避免把「加载中」和「确实为空」混成同一个结果。 */
const PANEL_CASES: Array<{
  name: string;
  input: { loading: boolean; loaded: boolean; total: number; visible: number };
  body: string;
  summary: boolean;
}> = [
  {
    name: "首次加载：还没有任何数据",
    input: { loading: true, loaded: false, total: 0, visible: 0 },
    body: "skeleton",
    summary: false,
  },
  {
    name: "首次加载失败：没有数据且请求已结束",
    input: { loading: false, loaded: false, total: 0, visible: 0 },
    body: "hidden",
    summary: false,
  },
  {
    name: "加载结束：一条自选都没有",
    input: { loading: false, loaded: true, total: 0, visible: 0 },
    body: "empty-watchlist",
    summary: false,
  },
  {
    name: "加入第一只标的的刷新：不闪「还没有自选标的」",
    input: { loading: true, loaded: true, total: 0, visible: 0 },
    body: "skeleton",
    summary: false,
  },
  {
    name: "加载结束：当前分组有标的",
    input: { loading: false, loaded: true, total: 3, visible: 2 },
    body: "rows",
    summary: true,
  },
  {
    name: "刷新中：已有行原样保留",
    input: { loading: true, loaded: true, total: 3, visible: 2 },
    body: "rows",
    summary: true,
  },
  {
    name: "加载结束：当前分组筛完为空",
    input: { loading: false, loaded: true, total: 3, visible: 0 },
    body: "empty-group",
    summary: true,
  },
  {
    name: "刷新中：空分组也摆占位行，不闪空状态",
    input: { loading: true, loaded: true, total: 3, visible: 0 },
    body: "skeleton",
    summary: true,
  },
];

describe("列表区与汇总面板的状态（AC4）", () => {
  PANEL_CASES.forEach(({ name, input, body, summary }) => {
    it(`${name} → ${body}`, () => {
      expect(watchlistPanelState(input).body).toBe(body);
    });

    it(`${name} → 汇总面板${summary ? "出现" : "不出现"}`, () => {
      expect(watchlistPanelState(input).hasData).toBe(summary);
    });
  });

  it("首次加载只摆占位行，不落到任何空状态", () => {
    const { body } = watchlistPanelState({
      loading: true,
      loaded: false,
      total: 0,
      visible: 0,
    });

    expect(body).not.toBe("empty-group");
    expect(body).not.toBe("empty-watchlist");
  });

  it("加载中永远不画出空状态，也不在数据到达前画汇总", () => {
    const loadingCases = PANEL_CASES.filter((entry) => entry.input.loading);

    for (const entry of loadingCases) {
      const state = watchlistPanelState(entry.input);
      expect(state.body).not.toBe("empty-group");
      expect(state.body).not.toBe("empty-watchlist");
    }
    const firstLoad = watchlistPanelState({
      loading: true,
      loaded: false,
      total: 0,
      visible: 0,
    });
    expect(firstLoad.hasData).toBe(false);
  });

  it("加载失败不会退化成一张只有表头的空表格", () => {
    expect(
      watchlistPanelState({ loading: false, loaded: false, total: 0, visible: 0 }).body,
    ).toBe("hidden");
  });
});

describe("表格画法：只由状态决定，没有兜底值", () => {
  it("每个面板状态对应的表格画法", () => {
    const expected: Record<string, "skeleton" | "rows" | null> = {
      skeleton: "skeleton",
      rows: "rows",
      hidden: null,
      "empty-group": null,
      "empty-watchlist": null,
    };

    for (const { name, input } of PANEL_CASES) {
      const body = watchlistPanelState(input).body;
      expect([name, watchlistListState(body)]).toEqual([name, expected[body]]);
    }
  });

  it("空状态与隐藏状态都不画表格", () => {
    expect(watchlistListState("hidden")).toBeNull();
    expect(watchlistListState("empty-group")).toBeNull();
    expect(watchlistListState("empty-watchlist")).toBeNull();
  });
});

/** 分组筛选行的计数：与汇总面板同一个门控，没有数据时不写任何数字。 */
function renderFilter(counts: Record<string, number> | null, total: number | null): string {
  return renderToStaticMarkup(
    createElement(GroupFilter, {
      value: null,
      groups: ["美股", "加密"],
      counts,
      total,
      onChange: () => {},
    }),
  );
}

describe("AC1 加载中不显示分组计数", () => {
  it("数据没到手时按钮只写分组名，不写「全部 0」", () => {
    const text = plainText(renderFilter(null, null));

    expect(text).toBe("全部美股加密");
    expect(text).not.toMatch(/\d/);
  });

  it("数据到达后写真实计数", () => {
    expect(plainText(renderFilter({ 美股: 6, 加密: 0 }, 6))).toBe("全部 6美股 6加密 0");
  });
});

describe("AC1 占位行：表头与 6 条占位行立即出现", () => {
  const html = renderList([], { state: "skeleton", loading: true });

  it("表头 + 6 条占位行，一共 7 行", () => {
    expect(count(html, "<tr ")).toBe(7);
    expect(count(html, 'class="wl-row')).toBe(6);
  });

  it("表格带 aria-busy 与可读的 aria-label，占位主体对读屏隐藏", () => {
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain('aria-label="关注列表加载中"');
    expect(count(html, '<tbody aria-hidden="true"')).toBe(1);
  });

  it("四列各一块呼吸色块，标的列两块（标的 + 产品键占两行）", () => {
    // 每行 5 块：标的 2 块，24H / 价格 / 信号各 1 块。
    expect(count(html, "animate-pulse")).toBe(6 * 5);
    expect(count(html, "bg-muted")).toBe(6 * 5);
    expect(count(html, '<td class="wl-col-24h')).toBe(6);
  });
});

describe("AC2 不跳动：占位行与真实行共用同一行高与表头", () => {
  it("占位行与真实行都带 51px 的 .wl-row 类", () => {
    expect(count(renderList([], { state: "skeleton", loading: true }), 'class="wl-row')).toBe(6);
    expect(count(renderList(ITEMS), 'class="wl-row')).toBe(ITEMS.length);
  });

  it("表头在占位状态与数据状态下一模一样", () => {
    expect(head(renderList([], { state: "skeleton", loading: true }))).toBe(head(renderList(ITEMS)));
    expect(count(head(renderList(ITEMS)), "<th ")).toBe(4);
  });
});

describe("AC3 刷新：保留原行只盖遮罩", () => {
  it("刷新期间原行仍在 DOM 里，并出现一层遮罩", () => {
    const html = renderList(ITEMS, { state: "rows", loading: true });

    expect(html).toContain('data-testid="watchlist-refreshing"');
    expect(html).toContain("bg-background/50");
    expect(count(html, 'class="wl-row')).toBe(ITEMS.length);
    ITEMS.forEach((item) => expect(html).toContain(item.instrument.inst_id));
  });

  it("刷新结束后遮罩与 aria-busy 一起消失", () => {
    const html = renderList(ITEMS);

    expect(html).not.toContain("watchlist-refreshing");
    expect(html).not.toContain("aria-busy");
    expect(count(html, 'class="wl-row')).toBe(ITEMS.length);
  });

  it("占位状态不画遮罩：此时没有已有行可盖", () => {
    expect(renderList([], { state: "skeleton", loading: true })).not.toContain(
      "watchlist-refreshing",
    );
  });
});

describe("AC6 表头唯一：骨架与真实表格共用同一份定义", () => {
  it("骨架表格与真实表格的 <thead> 完全相同", () => {
    const skeletonHead = head(renderList([], { state: "skeleton", loading: true }));
    const rowsHead = head(renderList(ITEMS));

    expect(skeletonHead).toBe(rowsHead);
    expect(count(skeletonHead, "<th ")).toBe(4);
  });

  it("两份表格的 colgroup 也相同", () => {
    const columns = (html: string): string =>
      html.slice(html.indexOf("<colgroup>"), html.indexOf("</colgroup>"));

    expect(columns(renderList([], { state: "skeleton", loading: true }))).toBe(
      columns(renderList(ITEMS)),
    );
  });
});
