import { describe, expect, it } from "vitest";

import type { components } from "../api/types";
import {
  collectMarketEvents,
  eventGroup,
  eventGroupLabel,
  eventTypeLabel,
  eventsForTicker,
  mergeMarketEvents,
  marketItemStatusLabel,
  overviewStaleNotice,
  pointsWithSources,
  summarySourceHref,
  summarySourceLabel,
} from "./market";

type MarketOverviewItem = components["schemas"]["MarketOverviewItem"];
type MarketEvent = components["schemas"]["MarketEventItem"];
type AiSummaryPoint = components["schemas"]["AiSummaryPoint"];
type AiSummarySource = components["schemas"]["AiSummarySource"];

function item(overrides: Partial<MarketOverviewItem> = {}): MarketOverviewItem {
  return {
    symbol: "NASDAQ",
    name: "NASDAQ Composite",
    value: "18000.12",
    change: "180",
    change_pct: "1.01",
    market_session: "closed",
    source: "market_data_provider",
    as_of: "2026-11-15T06:00:00Z",
    is_delayed: false,
    quality_status: "normal",
    source_url: null,
    ...overrides,
  };
}

function source(overrides: Partial<AiSummarySource> = {}): AiSummarySource {
  return { type: "market_overview", id: "NASDAQ", url: null, ...overrides };
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
    expect(
      overviewStaleNotice({ stale: true, stale_reason: "外部行情数据已过期: NASDAQ" }),
    ).toBe("数据已过期：外部行情数据已过期: NASDAQ");
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

  it("新闻可点回原始链接，提醒与指标点回首页对应区块", () => {
    expect(summarySourceHref(source({ type: "news", url: "https://example.test/news" }))).toBe(
      "https://example.test/news",
    );
    expect(summarySourceHref(source({ type: "news", url: null }))).toBeNull();
    expect(summarySourceHref(source({ type: "alert", id: "alert_1" }))).toBe("#alerts");
    expect(summarySourceHref(source({ type: "market_overview", id: "NASDAQ" }))).toBe(
      "#market-overview",
    );
    expect(summarySourceHref(source({ type: "risk", id: "risk_1" }))).toBe("#risk");
  });

  it("来源类型写中文，不把英文枚举直接露给用户", () => {
    expect(summarySourceLabel("news")).toBe("新闻");
    expect(summarySourceLabel("alert")).toBe("提醒");
    expect(summarySourceLabel("market_overview")).toBe("市场概况");
    expect(summarySourceLabel("risk")).toBe("风险");
  });
});

describe("宏观、财报与公告事件分类", () => {
  it("按事件类型归入宏观、财报、公告或其他，未知类型不硬猜", () => {
    expect(eventGroup("economic")).toBe("macro");
    expect(eventGroup("earnings")).toBe("earnings");
    expect(eventGroup("announcement")).toBe("announcement");
    expect(eventGroup("dividend")).toBe("announcement");
    expect(eventGroup("custom_unknown")).toBe("other");
  });

  it("分组标题与事件类型都有中文文案，未知类型保留原值", () => {
    expect(eventGroupLabel("macro")).toBe("宏观事件");
    expect(eventGroupLabel("earnings")).toBe("财报");
    expect(eventGroupLabel("announcement")).toBe("公告与新闻");
    expect(eventGroupLabel("other")).toBe("其他事件");
    expect(eventTypeLabel("earnings")).toBe("财报");
    expect(eventTypeLabel("custom_unknown")).toBe("custom_unknown");
  });

  it("详情页保留全局宏观事件和当前标的事件，排除其他标的", () => {
    const event = (ticker: string | null) =>
      ({ ticker, event_type: "economic", title: "事件" }) as MarketEvent;
    const events = [event(null), event("AAPL"), event("aapl"), event("MSFT")];
    expect(eventsForTicker(events, "AAPL").map((item) => item.ticker)).toEqual([
      null,
      "AAPL",
      "aapl",
    ]);
  });

  it("当前标的事件与全局事件按 id 合并去重", () => {
    const event = (id: string) => ({ id, ticker: null }) as MarketEvent;
    const merged = mergeMarketEvents([event("evt_1")], [event("evt_1"), event("evt_2")]);
    expect(merged.map((item) => item.id)).toEqual(["evt_1", "evt_2"]);
  });

  it("两路事件查询中一路失败时保留成功数据与失败原因", () => {
    const failure = new Error("全局事件读取超时");
    const result = collectMarketEvents([
      { status: "fulfilled", value: { items: [{ id: "evt_1" } as MarketEvent] } },
      { status: "rejected", reason: failure },
    ]);
    expect(result.events.map((item) => item.id)).toEqual(["evt_1"]);
    expect(result.failures).toEqual([failure]);
  });

  it("两路事件查询都失败时没有事件，两个失败原因都保留", () => {
    const result = collectMarketEvents([
      { status: "rejected", reason: new Error("标的查询失败") },
      { status: "rejected", reason: new Error("全局查询失败") },
    ]);
    expect(result.events).toEqual([]);
    expect(result.failures).toHaveLength(2);
  });

  it("两路事件查询都成功时没有失败原因", () => {
    const result = collectMarketEvents([
      { status: "fulfilled", value: { items: [{ id: "evt_1" } as MarketEvent] } },
      { status: "fulfilled", value: { items: [{ id: "evt_2" } as MarketEvent] } },
    ]);
    expect(result.events.map((item) => item.id)).toEqual(["evt_1", "evt_2"]);
    expect(result.failures).toEqual([]);
  });
});
