import { describe, expect, it } from "vitest";

import {
  buildLineChart,
  CHART_HEIGHT,
  CHART_WIDTH,
  closePoints,
  formatChartTime,
  type Candle,
} from "./chart";

function candle(close: string, open_time = "2026-11-10T07:00:00Z"): Candle {
  return {
    open: close,
    high: close,
    low: close,
    close,
    open_time,
    volume: "1520.335",
    is_closed: true,
    data_source: "okx",
  };
}

describe("closePoints", () => {
  it("只取收盘价与时间，其余价格字段不进入折线数据", () => {
    expect(closePoints([candle("231.42", "2026-11-10T07:00:00Z")])).toEqual([
      { time: "2026-11-10T07:00:00Z", price: "231.42" },
    ]);
  });
});

describe("buildLineChart", () => {
  it("没有任何收盘价时不产生任何图形", () => {
    const geometry = buildLineChart([]);
    expect(geometry.points).toEqual([]);
    expect(geometry.line).toBe("");
    expect(geometry.priceTicks).toEqual([]);
    expect(geometry.timeTicks).toEqual([]);
  });

  it("单点居中，路径只有一个起点", () => {
    const geometry = buildLineChart([{ time: "2026-11-10T07:00:00Z", price: "231.42" }]);

    expect(geometry.points).toHaveLength(1);
    const [point] = geometry.points;
    expect(point.x).toBeCloseTo((geometry.plotLeft + geometry.plotRight) / 2);
    expect(point.y).toBeGreaterThanOrEqual(geometry.plotTop);
    expect(point.y).toBeLessThanOrEqual(geometry.plotBottom);
    expect(geometry.line).toMatch(/^M[\d.]+ [\d.]+$/);
    expect(geometry.priceTicks).toHaveLength(4);
    expect(geometry.timeTicks).toHaveLength(1);
  });

  it("收盘价越高 y 越小：三个连续上涨的点，折线逐点向上", () => {
    const geometry = buildLineChart([
      { time: "2026-11-10T06:00:00Z", price: "100" },
      { time: "2026-11-10T07:00:00Z", price: "101" },
      { time: "2026-11-10T08:00:00Z", price: "102" },
    ]);

    expect(geometry.points[1].y).toBeLessThan(geometry.points[0].y);
    expect(geometry.points[2].y).toBeLessThan(geometry.points[1].y);
    expect(geometry.line.startsWith("M")).toBe(true);
    expect(geometry.line.split("L")).toHaveLength(3);
  });

  it("全平盘不产生 NaN 坐标，价格刻度文案不重复", () => {
    const geometry = buildLineChart([
      { time: "2026-11-10T06:00:00Z", price: "100" },
      { time: "2026-11-10T07:00:00Z", price: "100" },
      { time: "2026-11-10T08:00:00Z", price: "100" },
    ]);

    const yCoordinates = geometry.points.map((point) => point.y);
    expect(yCoordinates.every((value) => Number.isFinite(value))).toBe(true);
    expect(
      yCoordinates.every((value) => value >= 0 && value <= CHART_HEIGHT),
    ).toBe(true);
    expect(
      geometry.points.every((point) => Number.isFinite(point.x) && point.x >= 0),
    ).toBe(true);
    expect(geometry.points.every((point) => point.x <= CHART_WIDTH)).toBe(true);

    const labels = geometry.priceTicks.map((tick) => tick.label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("时间刻度最多 6 个且覆盖首尾", () => {
    const points = Array.from({ length: 9 }, (_, index) => ({
      time: `2026-11-10T0${index}:00:00Z`,
      price: String(100 + index),
    }));
    const geometry = buildLineChart(points);

    expect(geometry.timeTicks).toHaveLength(6);
    expect(geometry.timeTicks[0].label).toBe("11-10 00:00");
    expect(geometry.timeTicks[5].label).toBe("11-10 08:00");
    expect(geometry.timeTicks[0].x).toBeCloseTo(geometry.points[0].x);
    expect(geometry.timeTicks[5].x).toBeCloseTo(geometry.points[8].x);
  });

  it("价格无法解析的点被丢弃，不会画出 NaN 坐标", () => {
    expect(buildLineChart([{ time: "2026-11-10T07:00:00Z", price: "" }]).points).toEqual([]);
    expect(buildLineChart([{ time: "2026-11-10T07:00:00Z", price: "abc" }]).points).toEqual([]);
  });
});

describe("formatChartTime", () => {
  it("按 UTC 呈现月-日 时:分", () => {
    expect(formatChartTime("2026-11-10T07:00:00Z")).toBe("11-10 07:00");
  });

  it("无法解析时原样返回", () => {
    expect(formatChartTime("not-a-time")).toBe("not-a-time");
  });
});
