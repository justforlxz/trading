import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, request } from "./api";

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
