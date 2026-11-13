import { describe, expect, it } from "vitest";

import type { InstrumentRef } from "./api";
import {
  coverageText,
  dataTimeText,
  matchesCategory,
  metricText,
  ratioPercent,
  shortUtc,
  trendLabel,
  trendText,
} from "./watchlist";

const stockSwap: InstrumentRef = {
  inst_id: "AAPL-USDT-SWAP",
  inst_type: "SWAP",
  product_key: "AAPL",
  asset_type: "tokenized_equity",
  base_currency: "AAPL",
  quote_currency: "USDT",
};

const stockSpot: InstrumentRef = { ...stockSwap, inst_id: "XAAPL-USDT", inst_type: "SPOT" };
const cryptoSpot: InstrumentRef = {
  ...stockSwap,
  inst_id: "BTC-USDT",
  inst_type: "SPOT",
  product_key: "BTC",
  asset_type: "crypto",
};
const commodity: InstrumentRef = {
  ...stockSpot,
  inst_id: "XAUT-USDT",
  product_key: "XAUT",
  asset_type: "commodity_token",
};

describe("自选分类", () => {
  it("全部包含所有类别", () => {
    for (const instrument of [stockSwap, stockSpot, cryptoSpot, commodity]) {
      expect(matchesCategory(instrument, "all")).toBe(true);
    }
  });

  it("股票永续只包含代币化股票的永续", () => {
    expect(matchesCategory(stockSwap, "stock_swap")).toBe(true);
    expect(matchesCategory(stockSpot, "stock_swap")).toBe(false);
    expect(matchesCategory(cryptoSpot, "stock_swap")).toBe(false);
  });

  it("加密只包含加密资产，不把商品代币算进来", () => {
    expect(matchesCategory(cryptoSpot, "crypto")).toBe(true);
    expect(matchesCategory(stockSwap, "crypto")).toBe(false);
    expect(matchesCategory(commodity, "crypto")).toBe(false);
  });
});

describe("缺数据文案", () => {
  it("没有 K 线写尚未同步，有 K 线但指标不足写未生成", () => {
    expect(metricText(null, "missing")).toBe("尚未同步");
    expect(metricText(null, "partial")).toBe("未生成");
    expect(metricText("61.4", "ok")).toBe("61.4");
    expect(trendText(null, "missing")).toBe("尚未同步");
    expect(trendText(null, "partial")).toBe("未生成");
  });

  it("趋势枚举翻译为中文，未知值也不编造方向", () => {
    expect(trendLabel("bullish")).toBe("偏多");
    expect(trendLabel("bearish")).toBe("偏空");
    expect(trendLabel("neutral")).toBe("中性");
    expect(trendLabel(null)).toBe("未生成");
  });

  it("K 线覆盖与数据时间不把空值写成 0", () => {
    expect(coverageText({ candle_count: 0, data_status: "missing" })).toBe("尚未同步");
    expect(coverageText({ candle_count: 3, data_status: "partial" })).toBe(
      "日线 3 根 · 指标待补",
    );
    expect(coverageText({ candle_count: 846, data_status: "ok" })).toBe("日线 846 根");
    expect(dataTimeText(null)).toBe("尚未同步");
    expect(dataTimeText("2026-11-12T16:00:00Z")).toBe("最新日线 11-12 16:00 UTC");
    expect(shortUtc("2026-11-12T16:00:00Z")).toBe("11-12 16:00 UTC");
  });
});

describe("市场环境比率", () => {
  it("只做百分比换算，空值写未生成", () => {
    expect(ratioPercent("0.62")).toBe("62%");
    expect(ratioPercent(null)).toBe("未生成");
  });
});
