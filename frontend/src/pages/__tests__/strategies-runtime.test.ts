import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import type { StrategyRuntimeResponse } from "../../lib/api";
import {
  StrategyRuntimeStatusCard,
  type StrategyRuntimeStatusCardProps,
} from "../strategies/runtime-status";

const RUNTIME: StrategyRuntimeResponse = {
  checked_at: "2026-11-16T01:30:00Z",
  signal_scan: { status: "not_implemented", detail: "策略信号扫描尚未实现" },
  auto_execution: {
    enabled: false,
    detail: "自动执行默认关闭，只保存开关，不产生真实订单",
  },
};

function props(overrides: Partial<StrategyRuntimeStatusCardProps> = {}): StrategyRuntimeStatusCardProps {
  return {
    runtime: RUNTIME,
    loading: false,
    error: null,
    marketSubscription: "connected",
    ...overrides,
  };
}

function render(overrides: Partial<StrategyRuntimeStatusCardProps> = {}): string {
  return renderToStaticMarkup(createElement(StrategyRuntimeStatusCard, props(overrides)));
}

describe("策略页运行状态", () => {
  it("展示四项状态，扫描写未实现，自动执行写关闭", () => {
    const html = render();
    for (const label of ["运行状态", "信号扫描", "行情订阅", "自动执行", "最近检查时间"]) {
      expect(html).toContain(label);
    }
    expect(html).toContain("未实现");
    expect(html).toContain("策略信号扫描尚未实现");
    expect(html).toContain("已关闭");
    expect(html).toContain("不产生真实订单");
  });

  it("行情订阅显示推送层状态，检查时间按北京时间展示后端值", () => {
    const html = render({ marketSubscription: "disconnected" });
    expect(html).toContain("未连接");
    expect(html).toContain("来自 /api/stream 推送层");
    expect(html).toContain("2026-11-16 09:30（北京时间）");
    expect(html).toContain("由后端返回，不在前端推算");
  });

  it("后端读取失败时四项都写读取失败，不显示编造数值", () => {
    const html = render({ runtime: null, error: "运行状态加载失败" });
    expect(html.match(/读取失败/g)).toHaveLength(3);
    expect(html).toContain("运行状态加载失败");
  });
});
