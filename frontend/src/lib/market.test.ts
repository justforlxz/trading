import { describe, expect, it } from "vitest";

import type { components } from "../api/types";
import {
  marketItemStatusLabel,
  overviewStaleNotice,
  pointsWithSources,
  summarySourceHref,
  summarySourceLabel,
} from "./market";

type MarketOverviewItem = components["schemas"]["MarketOverviewItem"];
type AiSummaryPoint = components["schemas"]["AiSummaryPoint"];
type AiSummarySource = components["schemas"]["AiSummarySource"];

function item(overrides: Partial<MarketOverviewItem> = {}): MarketOverviewItem {
  return {
    symbol: "BTC-USDT",
    name: "Bitcoin",
    value: "90000.12",
    change: "900",
    change_pct: "1.01",
    market_session: "regular",
    source: "okx_spot",
    as_of: "2026-11-15T06:00:00Z",
    is_delayed: false,
    quality_status: "normal",
    source_url: null,
    ...overrides,
  };
}

function source(overrides: Partial<AiSummarySource> = {}): AiSummarySource {
  return { type: "market_overview", id: "BTC-USDT", url: null, ...overrides };
}

function point(sources: AiSummarySource[], text = "事实点"): AiSummaryPoint {
  return { text, sources };
}

describe("市场概况的延迟与过期状态", () => {
  it("normal 且不延迟写实时，延迟报价写延迟", () => {
    expect(marketItemStatusLabel(item())).toBe("实时");
    expect(marketItemStatusLabel(item({ is_delayed: true }))).toBe("延迟");
    expect(marketItemStatusLabel(item({ quality_status: "delayed" }))).toBe("延迟");
  });

  it("stale、missing、abnormal 各自写明确状态，不混成延迟", () => {
    expect(marketItemStatusLabel(item({ quality_status: "stale" }))).toBe("过期");
    expect(marketItemStatusLabel(item({ quality_status: "missing" }))).toBe("缺失");
    expect(marketItemStatusLabel(item({ quality_status: "abnormal" }))).toBe("异常");
  });

  it("顶层 stale 为真时必须给出显式提示，并带后端原因", () => {
    expect(overviewStaleNotice({ stale: false, stale_reason: null })).toBeNull();
    expect(overviewStaleNotice({ stale: true, stale_reason: "OKX BTC 行情已过期" })).toBe(
      "数据已过期：OKX BTC 行情已过期",
    );
    expect(overviewStaleNotice({ stale: true, stale_reason: null })).toBe(
      "数据已过期，不能当作实时值。",
    );
  });
});

describe("摘要事实点的来源", () => {
  it("没有来源或来源标识为空的事实点不展示", () => {
    const points = [
      point([source()], "保留"),
      point([], "没有来源"),
      point([source({ id: "  " })], "来源标识为空"),
    ];
    expect(pointsWithSources(points).map((entry) => entry.text)).toEqual(["保留"]);
  });

  it("提醒、市场概况与风险点回首页对应区块", () => {
    expect(summarySourceHref(source({ type: "alert", id: "alert_1" }))).toBe("#alerts");
    expect(summarySourceHref(source({ type: "market_overview", id: "BTC-USDT" }))).toBe(
      "#market-overview",
    );
    expect(summarySourceHref(source({ type: "risk", id: "risk_1" }))).toBe("#risk");
  });

  it("来源类型写中文，不把英文枚举直接露给用户", () => {
    expect(summarySourceLabel("alert")).toBe("提醒");
    expect(summarySourceLabel("market_overview")).toBe("市场概况");
    expect(summarySourceLabel("risk")).toBe("风险");
  });
});
