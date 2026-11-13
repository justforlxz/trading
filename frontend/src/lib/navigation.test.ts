import { describe, expect, it } from "vitest";

import { currentSection, isNavActive, type NavTarget } from "./navigation";

const ITEMS: NavTarget[] = [
  { to: "/", label: "概览", end: true },
  { to: "/watchlist", label: "自选" },
  { to: "/positions", label: "持仓" },
  { to: "/strategies", label: "策略与回测", alsoMatch: ["/backtests"] },
  { to: "/journal", label: "记录" },
  { to: "/settings", label: "设置" },
];

describe("isNavActive", () => {
  it("概览只在根路径高亮", () => {
    expect(isNavActive(ITEMS[0], "/")).toBe(true);
    expect(isNavActive(ITEMS[0], "/watchlist")).toBe(false);
  });

  it("自选在详情子路径下仍然高亮", () => {
    expect(isNavActive(ITEMS[1], "/watchlist/XAAPL-USDT")).toBe(true);
  });

  it("策略与回测把回测详情算作同一区块", () => {
    expect(isNavActive(ITEMS[3], "/strategies")).toBe(true);
    expect(isNavActive(ITEMS[3], "/backtests/run-1")).toBe(true);
    expect(isNavActive(ITEMS[3], "/settings")).toBe(false);
  });
});

describe("currentSection", () => {
  it("按当前路径返回主导航名称", () => {
    expect(currentSection("/", ITEMS)).toBe("概览");
    expect(currentSection("/positions", ITEMS)).toBe("持仓");
    expect(currentSection("/journal", ITEMS)).toBe("记录");
  });

  it("标的详情归到自选区块", () => {
    expect(currentSection("/watchlist/AAPL-USDT", ITEMS)).toBe("自选");
  });

  it("回测详情归到策略与回测区块", () => {
    expect(currentSection("/backtests/run-1", ITEMS)).toBe("策略与回测");
  });

  it("未知路径回退到概览", () => {
    expect(currentSection("/unknown", ITEMS)).toBe("概览");
  });
});
