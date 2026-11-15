import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import { AlertList } from "./alert-list";

const ITEMS = [
  {
    id: "al_warning",
    type: "risk" as const,
    severity: "warning",
    instrument_id: "AAPL-USDT-SWAP",
    rule_id: "stop_missing",
    title: "持仓缺少止损",
    detail: "AAPL-USDT-SWAP 没有有效止损记录",
    triggered_at: "2026-11-10T09:00:00Z",
  },
  {
    id: "al_critical",
    type: "risk" as const,
    severity: "critical",
    instrument_id: "AAPL-USDT-SWAP",
    rule_id: "margin_usage",
    title: "保证金使用率过高",
    detail: "保证金使用率超过阈值",
    triggered_at: "2026-11-10T08:00:00Z",
  },
];

describe("提醒列表", () => {
  it("按接口字段展示，严重提醒排在最前", () => {
    const html = renderToStaticMarkup(createElement(AlertList, { items: ITEMS }));
    expect(html.indexOf("保证金使用率过高")).toBeLessThan(html.indexOf("持仓缺少止损"));
    expect(html).toContain("严重");
    expect(html).toContain("警告");
    expect(html).toContain("AAPL-USDT-SWAP 没有有效止损记录");
    expect(html).toContain("规则 stop_missing");
    expect(html).toContain("标的 AAPL-USDT-SWAP");
  });

  it("提供处置回调时出现确认与忽略按钮", () => {
    const html = renderToStaticMarkup(
      createElement(AlertList, { items: ITEMS, onResolve: () => undefined }),
    );
    expect(html).toContain("确认");
    expect(html).toContain("忽略");
  });

  it("空列表使用明确文案", () => {
    const html = renderToStaticMarkup(
      createElement(AlertList, { items: [], emptyText: "当前标的没有待处理提醒。" }),
    );
    expect(html).toContain("当前标的没有待处理提醒。");
  });
});
