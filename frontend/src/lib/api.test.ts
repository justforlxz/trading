import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  fetchAiSummary,
  fetchMarketEvents,
  fetchMarketOverview,
  fetchNews,
  request,
} from "./api";

function respond(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("HTTP 客户端错误归一", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("响应不是 JSON 时给出可读提示，不暴露解析器原文", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(respond("<html>gateway error</html>")),
    );

    await expect(request("/dashboard/summary")).rejects.toBeInstanceOf(ApiError);
    await expect(request("/dashboard/summary")).rejects.toThrow(
      "请求失败（HTTP 200，响应不是有效的 JSON）",
    );
  });

  it("错误响应按 detail 归一", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(respond(JSON.stringify({ detail: "账户未配置" }), 400)),
    );

    await expect(request("/dashboard/summary")).rejects.toThrow("账户未配置");
  });
});

describe("市场数据接口", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("市场概况与事件按契约路径读取，事件带标的筛选", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond(JSON.stringify({ items: [] })))
      .mockResolvedValueOnce(respond(JSON.stringify({ items: [] })))
      .mockResolvedValueOnce(respond(JSON.stringify({ items: [] })));
    vi.stubGlobal("fetch", fetchMock);

    await fetchMarketOverview();
    await fetchMarketEvents("AAPL", 20);
    await fetchNews("AAPL", 10);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/market/overview");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/market/events?limit=20&ticker=AAPL");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/news?limit=10&ticker=AAPL");
  });

  it("摘要以 POST 提交 include_news 与 news_limit，不把请求体拼进路径", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(JSON.stringify({ points: [] })));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAiSummary({ include_news: false, news_limit: 5 });

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/ai/summary");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ include_news: false, news_limit: 5 });
  });
});
