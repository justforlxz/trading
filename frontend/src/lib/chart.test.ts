import { describe, expect, it } from "vitest";

import { buildCandleChart, CHART_HEIGHT, CHART_WIDTH, formatCandleTime, type Candle } from "./chart";

function candle(
  open: string,
  high: string,
  low: string,
  close: string,
  open_time = "2026-11-10T07:00:00Z",
): Candle {
  return {
    open,
    high,
    low,
    close,
    open_time,
    volume: "1520.335",
    is_closed: true,
    data_source: "okx",
  };
}

describe("buildCandleChart", () => {
  it("没有任何 K 线时不产生任何图形", () => {
    const geometry = buildCandleChart([]);
    expect(geometry.boxes).toEqual([]);
    expect(geometry.priceTicks).toEqual([]);
    expect(geometry.timeTicks).toEqual([]);
  });

  it("单根 K 线居中，影线与实体都落在绘图区内", () => {
    const geometry = buildCandleChart([candle("229.80", "232.10", "229.44", "231.42")]);

    expect(geometry.boxes).toHaveLength(1);
    const [box] = geometry.boxes;
    expect(box.centerX).toBeCloseTo((geometry.plotLeft + geometry.plotRight) / 2);
    expect(box.rising).toBe(true);
    expect(box.openY).toBeGreaterThan(box.closeY);
    expect(box.wickTop).toBeGreaterThanOrEqual(geometry.plotTop);
    expect(box.wickBottom).toBeLessThanOrEqual(geometry.plotBottom);
    expect(box.bodyTop).toBeGreaterThanOrEqual(box.wickTop);
    expect(box.bodyTop + box.bodyHeight).toBeLessThanOrEqual(box.wickBottom);
    expect(geometry.priceTicks).toHaveLength(5);
  });

  it("价格越高 y 越小：两根连续上涨的 K 线，后一根收盘更高", () => {
    const geometry = buildCandleChart([
      candle("100.00", "101.00", "99.00", "101.00", "2026-11-10T06:00:00Z"),
      candle("101.00", "103.00", "100.50", "102.00", "2026-11-10T07:00:00Z"),
    ]);

    expect(geometry.boxes[0].closeY).toBeLessThan(geometry.boxes[0].openY);
    expect(geometry.boxes[1].closeY).toBeLessThan(geometry.boxes[1].openY);
    expect(geometry.boxes[1].closeY).toBeLessThan(geometry.boxes[0].closeY);
  });

  it("全平盘 K 线不产生 NaN，实体保留最小可见高度", () => {
    const geometry = buildCandleChart([
      candle("100.00", "100.00", "100.00", "100.00", "2026-11-10T06:00:00Z"),
      candle("100.00", "100.00", "100.00", "100.00", "2026-11-10T07:00:00Z"),
    ]);

    const yCoordinates = geometry.boxes.flatMap((box) => [
      box.bodyTop,
      box.bodyHeight,
      box.openY,
      box.closeY,
      box.wickTop,
      box.wickBottom,
    ]);
    const xCoordinates = geometry.boxes.flatMap((box) => [box.centerX, box.bodyX, box.bodyWidth]);
    expect([...xCoordinates, ...yCoordinates].every((value) => Number.isFinite(value))).toBe(true);
    expect(yCoordinates.every((value) => value >= 0 && value <= CHART_HEIGHT)).toBe(true);
    expect(xCoordinates.every((value) => value >= 0 && value <= CHART_WIDTH)).toBe(true);
    expect(geometry.boxes[0].bodyHeight).toBeGreaterThanOrEqual(1);
    const labels = geometry.priceTicks.map((tick) => tick.label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("时间刻度最多 6 个且覆盖首尾 K 线", () => {
    const candles = Array.from({ length: 7 }, (_, index) =>
      candle("100", "101", "99", "100.5", `2026-11-10T0${index}:00:00Z`),
    );
    const geometry = buildCandleChart(candles);

    expect(geometry.timeTicks).toHaveLength(6);
    expect(geometry.timeTicks[0].label).toBe("11-10 00:00");
    expect(geometry.timeTicks[5].label).toBe("11-10 06:00");
    expect(geometry.timeTicks[0].x).toBeCloseTo(geometry.boxes[0].centerX);
    expect(geometry.timeTicks[5].x).toBeCloseTo(geometry.boxes[6].centerX);
  });

  it("价格无法解析的 K 线被丢弃，不会画出 NaN 坐标", () => {
    expect(buildCandleChart([candle("", "231", "229", "231")]).boxes).toEqual([]);
  });
});

describe("formatCandleTime", () => {
  it("按 UTC 呈现月-日 时:分", () => {
    expect(formatCandleTime("2026-11-10T07:00:00Z")).toBe("11-10 07:00");
  });

  it("无法解析时原样返回", () => {
    expect(formatCandleTime("not-a-time")).toBe("not-a-time");
  });
});
