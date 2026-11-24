import { describe, expect, it } from "vitest";

import {
  alertListQuery,
  alertStatusLabel,
  alertTypeLabel,
  severityLabel,
  sortAlertsBySeverity,
} from "./alerts";

describe("提醒展示辅助", () => {
  it("级别、类型与状态只做中文标签，未知值原样返回", () => {
    expect(severityLabel("critical")).toBe("紧急");
    expect(severityLabel("warning")).toBe("警告");
    expect(severityLabel(null)).toBe("未标注级别");
    expect(severityLabel("unknown-level")).toBe("unknown-level");
    expect(alertTypeLabel("risk")).toBe("持仓风险");
    expect(alertTypeLabel("indicator")).toBe("技术形态");
    expect(alertTypeLabel("market")).toBe("大盘异动");
    expect(alertTypeLabel("watchlist")).toBe("组合异动");
    expect(alertTypeLabel("other")).toBe("other");
    expect(alertStatusLabel("acknowledged")).toBe("已确认");
    expect(alertStatusLabel("other")).toBe("other");
  });

  it("严重在前，同一级别按触发时间倒序", () => {
    const ordered = sortAlertsBySeverity([
      { severity: "info", triggered_at: "2026-11-10T10:00:00Z" },
      { severity: "critical", triggered_at: "2026-11-10T08:00:00Z" },
      { severity: "warning", triggered_at: "2026-11-10T09:00:00Z" },
      { severity: "critical", triggered_at: "2026-11-10T12:00:00Z" },
    ]);
    expect(ordered.map((item) => `${item.severity}:${item.triggered_at}`)).toEqual([
      "critical:2026-11-10T12:00:00Z",
      "critical:2026-11-10T08:00:00Z",
      "warning:2026-11-10T09:00:00Z",
      "info:2026-11-10T10:00:00Z",
    ]);
  });

  it("筛选条件按接口参数名拼接，未设置的条件不出现", () => {
    const query = alertListQuery({ status: "pending", instrumentId: "AAPL-USDT-SWAP" });
    expect(query.get("status")).toBe("pending");
    expect(query.get("instrument_id")).toBe("AAPL-USDT-SWAP");
    expect(query.has("type")).toBe(false);
    expect(query.has("severity")).toBe(false);
  });
});
