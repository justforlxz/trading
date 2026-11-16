import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

import { describe, expect, it } from "vitest";

import type { InstrumentDetailResponse } from "../../lib/api";
import { InstrumentContractsCard } from "../instrument-detail/contracts-card";

type InstrumentInfo = InstrumentDetailResponse["instrument"];
type SiblingQuote = InstrumentDetailResponse["siblings"][number];

function instrument(overrides: Partial<InstrumentInfo> = {}): InstrumentInfo {
  return {
    asset_type: "tokenized_equity",
    base_currency: "BTC",
    inst_id: "BTC-USDT",
    inst_type: "SPOT",
    listing_time: "2024-01-01T00:00:00Z",
    lot_size: "0.00000001",
    max_leverage: "10",
    min_order_size: "0.00001",
    product_key: "BTC",
    quote_currency: "USDT",
    tick_size: "0.1",
    trading_status: "live",
    ...overrides,
  };
}

function sibling(overrides: Partial<SiblingQuote> = {}): SiblingQuote {
  return {
    inst_id: "BTC-USDT-SWAP",
    inst_type: "SWAP",
    last_price: "96500.5",
    price_spread_pct: "0.06",
    ...overrides,
  };
}

function render(
  overrides: Partial<Parameters<typeof InstrumentContractsCard>[0]> = {},
): string {
  return renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(InstrumentContractsCard, {
        instrument: instrument(),
        siblings: [sibling()],
        ...overrides,
      }),
    ),
  );
}

describe("详情页合约元数据与同一产品另一形态", () => {
  it("展示四项合约元数据，数值原样来自接口", () => {
    const html = render();

    expect(html).toContain("合约元数据");
    expect(html).toContain("最小价格变动 tick_size");
    expect(html).toContain("0.1");
    expect(html).toContain("下单数量精度 lot_size");
    expect(html).toContain("0.00000001");
    expect(html).toContain("最小下单量 min_order_size");
    expect(html).toContain("0.00001");
    expect(html).toContain("最大杠杆 max_leverage");
    expect(html).toContain("10");
  });

  it("字段没有同步时写未提供，不写 0 冒充", () => {
    const html = render({
      instrument: instrument({
        tick_size: null,
        lot_size: null,
        min_order_size: null,
        max_leverage: null,
      }),
    });

    expect(html.match(/>未提供<\/dd>/g)?.length).toBe(4);
    expect(html).not.toContain(">0<");
  });

  it("展示同一产品另一形态的代码、价格与带符号价差", () => {
    const html = render({ siblings: [sibling({ price_spread_pct: "-0.12" })] });

    expect(html).toContain("同一产品的另一形态");
    expect(html).toContain("现货与永续");
    expect(html).toContain("BTC-USDT-SWAP");
    expect(html).toContain("96500.5");
    expect(html).toContain("价差 -0.12%");
    expect(html).toContain('href="/watchlist/BTC-USDT-SWAP"');
  });

  it("另一形态没有可用报价时如实写未提供，不编造价差", () => {
    const html = render({ siblings: [] });

    expect(html).toContain("价差未提供");
    expect(html).not.toContain("价差 +");
  });

  it("读取另一形态失败时显示原因，合约元数据仍照常展示", () => {
    const html = render({ siblings: null, siblingsError: "另一形态读取失败" });

    expect(html).toContain("另一形态读取失败");
    expect(html).toContain("价差未提供");
    expect(html).toContain("0.00000001");
  });

  it("读取期间显示加载状态，不用未提供抢先占位", () => {
    const html = render({ siblings: null, siblingsLoading: true });

    expect(html).toContain("加载中");
    expect(html).not.toContain("价差未提供");
  });
});
