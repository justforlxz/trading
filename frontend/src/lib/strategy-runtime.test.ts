import { describe, expect, it } from "vitest";

import type { StrategyRuntimeResponse } from "./api";
import {
  autoExecutionLabel,
  marketSubscriptionLabel,
  marketSubscriptionStatus,
  signalScanLabel,
} from "./strategy-runtime";

const RUNTIME: StrategyRuntimeResponse = {
  checked_at: "2026-11-16T01:30:00Z",
  signal_scan: { status: "not_implemented", detail: "策略信号扫描尚未实现" },
  auto_execution: { enabled: false, detail: "自动执行默认关闭" },
};

describe("策略运行状态文案", () => {
  it("扫描未实现与自动执行关闭使用明确文字", () => {
    expect(signalScanLabel(RUNTIME.signal_scan)).toBe("未实现");
    expect(autoExecutionLabel(RUNTIME.auto_execution)).toBe("已关闭");
    expect(autoExecutionLabel({ ...RUNTIME.auto_execution, enabled: true })).toBe("已开启");
  });

  it("行情订阅只按推送层状态显示，未到达时保持等待", () => {
    expect(marketSubscriptionStatus({})).toBe("pending");
    expect(marketSubscriptionStatus({ public_ws: false })).toBe("disconnected");
    expect(marketSubscriptionStatus({ public_ws: true })).toBe("connected");
    expect(marketSubscriptionLabel("pending")).toBe("等待推送层状态");
    expect(marketSubscriptionLabel("disconnected")).toBe("未连接");
    expect(marketSubscriptionLabel("connected")).toBe("已连接");
  });
});
