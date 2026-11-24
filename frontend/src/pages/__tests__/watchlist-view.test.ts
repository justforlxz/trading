import { createElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { WatchlistItem } from "../../lib/api";
import { aggregateWatchlist, buildPendingDigest } from "../../lib/watchlist-summary";
import { GroupFilter } from "../watchlist/index";
import { WatchlistList } from "../watchlist/list";
import { Sparkline } from "../watchlist/sparkline";
import { WatchlistSummary } from "../watchlist/summary";
import { makeAlert, makeItem, makeSignal } from "./watchlist-fixtures";

/** 去掉标签只留文字，便于断言标签之间的渲染结果。 */
function plainText(html: string): string {
  return html.replace(/<[^>]*>/g, "");
}

function renderList(
  items: readonly WatchlistItem[],
  groups: readonly string[] = ["默认", "美股", "加密"],
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
        groups,
        onRemove: () => {},
        onMove: () => {},
        state: "rows",
      }),
    ),
  );
}

describe("关注列表结构（C-01 / C-02）", () => {
  const items = [
    makeItem("AAPL-USDT-SWAP", { change: "1.86", group: "美股" }),
    makeItem("BTC-USDT-SWAP", { change: "-0.44", group: "加密" }),
    makeItem("XSPCX-USDT", { change: null, group: "默认", dataStatus: "missing" }),
  ];

  it("表头固定 4 列：标的、24H、价格 / 涨跌、信号", () => {
    const html = renderList(items);
    // 只看表头，别把行内「无信号」里的「信号」也算进来。
    const headerText = plainText(html.slice(0, html.indexOf("<tbody")));

    expect(html.split("<th ").length - 1).toBe(4);
    expect(headerText).toBe("标的24H价格 / 涨跌信号");
  });

  it("RSI、ATR、K 线覆盖与最近更新时间不再出现在列表里", () => {
    const text = plainText(renderList(items));

    expect(text).not.toContain("RSI(14)");
    expect(text).not.toContain("ATR(14)%");
    expect(text).not.toContain("K 线覆盖");
    expect(text).not.toContain("最近更新时间");
    expect(text).not.toContain("日线");
  });

  it("24H 分时线单独占一列，没有收盘时画灰色虚线", () => {
    const html = renderList(items);

    expect(html).toContain('<col class="wl-col-24h"');
    // 每行一个分时线（另有每行的操作图标，因此按 viewBox 认）。
    expect(html.split('viewBox="0 0 76 30"').length - 1).toBe(items.length);
    expect(html).toContain("stroke-dasharray");
  });

  it("行内没有常驻分组输入框：分组改由行尾菜单「移动到分组」", () => {
    const html = renderList(items);

    expect(html).not.toContain("list=");
    expect(html).not.toContain("<datalist");
    expect(html).not.toContain("<input");
    // 每行一个菜单入口，菜单里先写分组动作，再列出各分组。
    expect(html.split('aria-label="AAPL-USDT-SWAP 的更多操作"').length - 1).toBe(1);
    expect(html).toContain("移动到分组");
    expect(html).toContain("默认 · 当前");
    expect(html).toContain(">美股</button>");
    expect(html).toContain(">加密</button>");
  });

  it("每个标的渲染一行，没有信号时写「无信号」并用灰色色条", () => {
    const html = renderList(items);

    expect(html.split("<tr ").length - 1).toBe(items.length + 1);
    expect(html).toContain("inset 3px 0 0 #d4d4d8");
    expect(plainText(html).match(/无信号/g)).toHaveLength(items.length);
  });

  it("BUY 信号用绿色色条，SELL 信号用琥珀色色条", () => {
    const html = renderList([
      makeItem("BUY-USDT-SWAP", { signal: makeSignal("BUY", "MA20 上穿 MA60") }),
      makeItem("SELL-USDT-SWAP", { signal: makeSignal("SELL", "跌破 MA20") }),
    ]);

    expect(html).toContain("inset 3px 0 0 #10b981");
    expect(html).toContain("inset 3px 0 0 #f59e0b");
    expect(plainText(html)).toContain("MA20 上穿 MA60");
  });
});

describe("分组筛选行（AC4）", () => {
  function renderFilter(value: string | null, groups: readonly string[]): string {
    return renderToStaticMarkup(
      createElement(GroupFilter, {
        value,
        groups,
        counts: Object.fromEntries(groups.map((name) => [name, 0])) as Record<string, number>,
        total: 3,
        onChange: () => {},
      }),
    );
  }

  it("显示全部、各分组与各自计数", () => {
    const html = renderFilter(null, ["美股", "加密"]);

    expect(plainText(html)).toBe("全部 3美股 0加密 0");
    expect(html).toContain('aria-label="分组筛选"');
  });

  it("选中某个分组时只有那一个按钮是按下状态", () => {
    const html = renderFilter("加密", ["美股", "加密"]);
    const pressed = html.match(/aria-pressed="true"/g) ?? [];

    expect(pressed).toHaveLength(1);
    expect(html).toContain(">加密 0</button>");
  });
});

describe("分时线", () => {
  it("少于两根收盘时画灰色虚线", () => {
    const empty = renderToStaticMarkup(createElement(Sparkline, { closes: [] }));
    const single = renderToStaticMarkup(createElement(Sparkline, { closes: [12.5] }));

    expect(empty).toContain("stroke-dasharray");
    expect(empty).toContain('viewBox="0 0 76 30"');
    expect(single).toContain("stroke-dasharray");
  });

  it("有真实收盘时画折线，不补点", () => {
    const closes = Array.from({ length: 24 }, (_, index) => 100 + index);
    const html = renderToStaticMarkup(createElement(Sparkline, { closes }));

    expect(html).toContain("<polyline");
    expect(html).not.toContain("stroke-dasharray");
  });
});

describe("关注汇总渲染（AC3 / AC4）", () => {
  it("AC3：上涨 1 / 下跌 1 / 平盘 / 无数据 1，平均 0.00%，有信号 0", () => {
    const items = [
      makeItem("A-USDT-SWAP", { change: "1" }),
      makeItem("B-USDT-SWAP", { change: "-1" }),
      makeItem("C-USDT-SWAP", { change: null }),
    ];
    const text = plainText(
      renderToStaticMarkup(
        createElement(WatchlistSummary, {
          aggregate: aggregateWatchlist(items),
          pending: buildPendingDigest(items, []),
          marketRisk: null,
        }),
      ),
    );

    expect(text).toContain("上涨 1");
    expect(text).toContain("下跌 1");
    expect(text).toContain("平盘 / 无数据 1");
    expect(text).toContain("有信号0");
    expect(text).toContain("平均涨跌0.00%");
    expect(text).toContain("需要处理0 项");
    expect(text).toContain("暂无待处理项");
  });

  it("AC4：3 条提醒显示 3 项；再加 4 条信号后出现「另有 1 项」", () => {
    const alerts = [
      makeAlert("al_1", "持仓缺少止损", "BTC-USDT"),
      makeAlert("al_2", "持仓缺少止损", "ETH-USDT"),
      makeAlert("al_3", "数据延迟", "SOL-USDT"),
    ];
    // 提醒挂的是现货标识，自选里是永续标识，靠归属规则对上。
    const quiet = [
      makeItem("BTC-USDT-SWAP"),
      makeItem("ETH-USDT-SWAP"),
      makeItem("SOL-USDT-SWAP"),
    ];

    const onlyAlerts = plainText(
      renderToStaticMarkup(
        createElement(WatchlistSummary, {
          aggregate: aggregateWatchlist(quiet),
          pending: buildPendingDigest(quiet, alerts),
          marketRisk: null,
        }),
      ),
    );

    expect(onlyAlerts).toContain("需要处理3 项");
    expect(onlyAlerts).not.toContain("另有");

    const withSignals = [
      ...quiet,
      makeItem("S1-USDT-SWAP", { signal: makeSignal("BUY", "MA20 上穿 MA60") }),
      makeItem("S2-USDT-SWAP", { signal: makeSignal("SELL", "跌破 MA20") }),
      makeItem("S3-USDT-SWAP", { signal: makeSignal("BUY", "MACD 金叉") }),
      makeItem("S4-USDT-SWAP", { signal: makeSignal("BUY", "放量突破") }),
    ];

    const crowded = plainText(
      renderToStaticMarkup(
        createElement(WatchlistSummary, {
          aggregate: aggregateWatchlist(withSignals),
          pending: buildPendingDigest(withSignals, alerts),
          marketRisk: null,
        }),
      ),
    );

    expect(crowded).toContain("需要处理7 项");
    expect(crowded).toContain("另有 1 项");
  });
});

describe("市场风险块（AC4）", () => {
  const vix = {
    series_id: "vix",
    name: "恐慌指数 VIX",
    unit: "点",
    granularity: "minute" as const,
    provider: "yahoo",
    source_url: null,
    value: "35.89",
    change: "7.45",
    as_of: "2026-11-20T20:59:00Z",
    is_delayed: true,
    market_session: "open",
    quality_status: "normal" as const,
    regime: "panic" as const,
    error: null,
  };

  function renderSummary(marketRisk: typeof vix | null): string {
    return plainText(
      renderToStaticMarkup(
        createElement(WatchlistSummary, {
          aggregate: aggregateWatchlist([makeItem("BTC-USDT-SWAP")]),
          pending: buildPendingDigest([], []),
          marketRisk,
        }),
      ),
    );
  }

  it("只展示全局风险读数：数值、分级与更新时间", () => {
    const text = renderSummary(vix);

    expect(text).toContain("市场风险");
    expect(text).toContain("35.89点");
    expect(text).toContain("恐慌");
    expect(text).toContain("更新");
    expect(text).not.toContain("国债");
    expect(text).not.toContain("利差");
  });

  it("读数缺失时写「缺失」，不编造数值", () => {
    const text = renderSummary(null);

    expect(text).toContain("市场风险");
    expect(text).toContain("缺失");
    expect(text).toContain("未分级");
  });
});
