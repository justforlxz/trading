import { createElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { WatchlistItem } from "../../lib/api";
import { aggregateWatchlist, buildPendingDigest } from "../../lib/watchlist-summary";
import { WatchlistList } from "../watchlist/list";
import { Sparkline } from "../watchlist/sparkline";
import { WatchlistSummary } from "../watchlist/summary";
import { makeAlert, makeItem, makeSignal } from "./watchlist-fixtures";

/** 去掉标签只留文字，便于断言标签之间的渲染结果。 */
function plainText(html: string): string {
  return html.replace(/<[^>]*>/g, "");
}

function renderList(items: readonly WatchlistItem[]): string {
  return renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(WatchlistList, {
        items,
        quotes: {},
        closes: {},
        busy: null,
        onRemove: () => {},
      }),
    ),
  );
}

describe("关注列表结构（MUST 2 / MUST 4）", () => {
  const items = [
    makeItem("AAPL-USDT-SWAP", { change: "1.86" }),
    makeItem("BTC-USDT-SWAP", { change: "-0.44" }),
    makeItem("XSPCX-USDT", { change: null, dataStatus: "missing" }),
  ];

  it("只有 4 列：标的、24H、价格 / 涨跌、信号", () => {
    const html = renderList(items);
    // 只看表头，别把行内「无信号」里的「信号」也算进来。
    const headerText = plainText(html.slice(0, html.indexOf("<tbody")));

    expect(html.split("<th ").length - 1).toBe(4);
    expect(headerText.match(/标的|24H|价格 \/ 涨跌|信号/g)).toEqual([
      "标的",
      "24H",
      "价格 / 涨跌",
      "信号",
    ]);
  });

  it("列宽按 44% / 18% / 22% / 16% 声明，表头与单元格共用同一组类", () => {
    const html = renderList(items);

    for (const className of [
      "wl-col-target",
      "wl-col-24h",
      "wl-col-price",
      "wl-col-signal",
      "wl-cell-first",
      "wl-cell-last",
    ]) {
      expect(html).toContain(`class="${className}`);
    }
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
        }),
      ),
    );

    expect(crowded).toContain("需要处理7 项");
    expect(crowded).toContain("另有 1 项");
  });
});
