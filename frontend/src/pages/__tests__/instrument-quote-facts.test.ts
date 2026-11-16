import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import { QuoteFactsLine } from "../instrument-detail";

function render(
  overrides: Partial<Parameters<typeof QuoteFactsLine>[0]> = {},
): string {
  return renderToStaticMarkup(
    createElement(QuoteFactsLine, {
      mark: "31.10",
      index: "31.12",
      updatedAt: "2026-11-16 17:45",
      source: "OKX WebSocket 推送",
      ...overrides,
    }),
  );
}

function occurrences(html: string, text: string): number {
  return html.split(text).length - 1;
}

describe("详情页头部下方行情信息行", () => {
  it("标记价、指数价、更新时间、来源各显示一次", () => {
    const html = render();

    for (const label of ["标记价", "指数价", "更新", "来源"]) {
      expect(occurrences(html, label)).toBe(1);
    }
    expect(html).toContain("31.10");
    expect(html).toContain("31.12");
    expect(html).toContain("2026-11-16 17:45");
    expect(html).toContain("OKX WebSocket 推送");
  });

  it("缺值写「尚未提供」，不填 0", () => {
    const html = render({ mark: null, index: null, updatedAt: null, source: null });

    expect(occurrences(html, "尚未提供")).toBe(4);
    expect(html).not.toContain(">0<");
  });
});
