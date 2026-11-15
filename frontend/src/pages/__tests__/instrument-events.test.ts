import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

import { describe, expect, it } from "vitest";

import type { MarketEvent, NewsArticle } from "../../lib/market";
import { EventsCardBody } from "../instrument-detail/events-card";

function event(overrides: Partial<MarketEvent> = {}): MarketEvent {
  return {
    id: "evt_1",
    event_type: "economic",
    title: "美国 CPI",
    region: "US",
    ticker: null,
    scheduled_at: "2026-11-17T13:30:00Z",
    scheduled_at_beijing: "2026-11-17 21:30",
    actual: null,
    forecast: "3.2",
    previous: "3.0",
    importance: "high",
    source: "market_data_provider",
    source_url: "https://example.test/events/1",
    received_at: "2026-11-15T06:10:00Z",
    ...overrides,
  };
}

function news(overrides: Partial<NewsArticle> = {}): NewsArticle {
  return {
    id: "news_1",
    title: "AAPL 发布季度业绩",
    summary: "收入高于市场预期。",
    publisher: "Example News",
    url: "https://example.test/news/1",
    published_at: "2026-11-15T05:00:00Z",
    tickers: ["AAPL"],
    tags: ["technology"],
    source: "market_data_provider",
    received_at: "2026-11-15T06:10:00Z",
    ...overrides,
  };
}

function render(overrides: Partial<Parameters<typeof EventsCardBody>[0]> = {}): string {
  return renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(EventsCardBody, {
        ticker: "AAPL",
        events: [
          event(),
          event({ id: "evt_2", event_type: "earnings", title: "AAPL 财报" }),
          event({ id: "evt_3", event_type: "announcement", title: "AAPL 公告" }),
          event({ id: "evt_4", event_type: "custom_unknown", title: "未知事件" }),
        ],
        news: [news()],
        eventsError: null,
        newsError: null,
        loading: false,
        ...overrides,
      }),
    ),
  );
}

describe("详情页近期事件", () => {
  it("按宏观、财报、公告与新闻分类展示，时间用接口给出的北京时间", () => {
    const html = render();
    expect(html).toContain("宏观事件");
    expect(html).toContain("财报");
    expect(html).toContain("公告与新闻");
    expect(html).toContain("其他事件");
    expect(html).toContain("美国 CPI");
    expect(html).toContain("2026-11-17 21:30");
    expect(html).toContain("AAPL 发布季度业绩");
    expect(html).toContain("https://example.test/events/1");
    expect(html).toContain("https://example.test/news/1");
  });

  it("没有事件和新闻时写空态，不编造条目", () => {
    const html = render({ events: [], news: [] });
    expect(html).toContain("当前没有已采集的宏观、财报、公告或新闻");
  });

  it("读取失败时显示接口原因，另一类数据仍照常展示", () => {
    const html = render({ eventsError: "事件读取失败", events: [] });
    expect(html).toContain("事件读取失败");
    expect(html).toContain("AAPL 发布季度业绩");
  });

  it("部分事件查询失败时同时展示已有事件与失败原因", () => {
    const html = render({ eventsError: "全局事件读取超时" });
    expect(html).toContain("全局事件读取超时");
    expect(html).toContain("美国 CPI");
  });

  it("新闻没有发布方时只显示来源，不重复写「来源」", () => {
    const html = render({ news: [news({ publisher: null })] });
    expect(html).toContain("来源 market_data_provider");
    expect(html).not.toContain("来源 · 来源 market_data_provider");
  });

  it("标的缺少产品代码时不发查询，明确说明原因", () => {
    const html = render({ ticker: null });
    expect(html).toContain("无法确定标的代码");
  });
});
