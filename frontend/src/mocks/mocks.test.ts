import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { setupServer } from "msw/node";

import { handlers } from "./handlers";

const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const BASE = "http://localhost";

/**
 * 九个业务域各挑一个最常用的端点：任何一个没有 handler，前端就无法独立开发。
 */
const DOMAIN_PROBES = [
  ["watchlist", "/api/watchlist"],
  ["indicators", "/api/indicators"],
  ["strategy", "/api/strategies"],
  ["backtest", "/api/backtests?data_source=okx"],
  ["settings", "/api/settings"],
  ["dashboard", "/api/dashboard/summary"],
  ["correlation", "/api/correlation/matrix?bar=1d&window=60&product_keys=AAPL"],
  ["opportunity", "/api/opportunities"],
  ["approval", "/api/approvals"],
] as const;

describe("MSW 假后端", () => {
  it.each(DOMAIN_PROBES)("%s 域至少有一个端点可响应", async (_domain, url) => {
    const response = await fetch(`${BASE}${url}`);

    expect(response.status).toBe(200);
    const body: unknown = await response.json();
    expect(body).toBeTruthy();
  });

  it("handler 内不出现内联业务数据（数据只能来自 fixture）", async () => {
    const source = await readFile(fileURLToPath(new URL("./handlers.ts", import.meta.url)), "utf8");

    // 内联数据只在 `key: value` 形态出现；handler 只允许 path 字符串与 status。
    expect(source).not.toMatch(/"(inst_id|symbol|last_price|equity)"\s*:/);
  });
});
