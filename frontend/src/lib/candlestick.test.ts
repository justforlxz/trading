import { describe, expect, it } from "vitest";

import type { InstrumentAnalysisCandle } from "./api";
import { buildCandlestickChart, type CandlestickInput } from "./candlestick";
import { formatBeijingTime } from "./display";

function candle(
  openTime: string,
  open: string,
  high: string,
  low: string,
  close: string,
  volume = "100",
): InstrumentAnalysisCandle {
  return {
    open_time: openTime,
    open,
    high,
    low,
    close,
    volume,
    is_closed: true,
    data_source: "okx_spot",
  };
}

function input(
  candles: InstrumentAnalysisCandle[],
  overrides: Partial<CandlestickInput> = {},
): CandlestickInput {
  return {
    gaps: [],
    candles,
    overlays: [],
    ...overrides,
  };
}

describe("buildCandlestickChart", () => {
  it("没有 K 线时不产生任何图形", () => {
    const geometry = buildCandlestickChart(input([]));

    expect(geometry.candles).toEqual([]);
    expect(geometry.overlays).toEqual([]);
    expect(geometry.priceTicks).toEqual([]);
  });

  it("按开高低收摆放蜡烛，上涨与下跌分开标记", () => {
    const geometry = buildCandlestickChart(
      input([
        candle("2026-11-10T16:00:00Z", "100", "103", "99", "102"),
        candle("2026-11-11T16:00:00Z", "102", "104", "98", "99"),
      ]),
    );

    expect(geometry.candles).toHaveLength(2);
    const [up, down] = geometry.candles;
    expect(up.up).toBe(true);
    expect(down.up).toBe(false);
    expect(up.highY).toBeLessThan(up.lowY);
    expect(up.bodyTop).toBeLessThan(up.bodyBottom);
    expect(up.bodyX).toBeGreaterThanOrEqual(geometry.plotLeft);
    expect(down.bodyX).toBeLessThanOrEqual(geometry.plotRight);
  });

  it("均线只连到有 K 线的时刻，缺口标在两根 K 线之间", () => {
    const geometry = buildCandlestickChart(
      input(
        [
          candle("2026-11-10T16:00:00Z", "100", "101", "99", "100"),
          candle("2026-11-14T16:00:00Z", "100", "101", "99", "100"),
        ],
        {
          gaps: [
            {
              start: "2026-11-11T16:00:00Z",
              end: "2026-11-14T16:00:00Z",
              missing: 3,
            },
          ],
          overlays: [
            {
              name: "MA20",
              points: [
                { time: "2026-11-10T16:00:00Z", value: "100" },
                { time: "2026-11-11T16:00:00Z", value: "101" },
                { time: "2026-11-14T16:00:00Z", value: "102" },
              ],
            },
          ],
        },
      ),
    );

    expect(geometry.overlays).toHaveLength(1);
    expect(geometry.overlays[0].path.split("L")).toHaveLength(2);
    expect(geometry.gaps).toHaveLength(1);
    expect(geometry.gaps[0].missing).toBe(3);
    expect(geometry.gaps[0].left).toBeLessThan(geometry.gaps[0].right);
  });

  it("成交量柱落在成交量窗格内", () => {
    const geometry = buildCandlestickChart(
      input([
        candle("2026-11-10T16:00:00Z", "100", "101", "99", "100", "10"),
        candle("2026-11-11T16:00:00Z", "100", "101", "99", "100", "20"),
      ]),
    );

    for (const row of geometry.candles) {
      expect(row.volumeY).toBeGreaterThanOrEqual(geometry.volumeTop - 1);
      expect(row.volumeY + row.volumeHeight).toBeLessThanOrEqual(geometry.volumeBottom + 1);
    }
  });

  it("成交标记落在对应 K 线上，没有 K 线的标记不绘制也不插值", () => {
    const geometry = buildCandlestickChart(
      input(
        [
          candle("2026-11-10T16:00:00Z", "100", "103", "99", "102"),
          candle("2026-11-11T16:00:00Z", "102", "104", "98", "99"),
        ],
        {
          markers: [
            {
              trade_id: "tr_0001",
              kind: "entry",
              time: "2026-11-10T16:00:00Z",
              price: "101",
              side: "buy",
              qty: "8.63",
            },
            {
              trade_id: "tr_0001",
              kind: "exit",
              time: "2026-11-11T16:00:00Z",
              price: "99",
              side: "sell",
              qty: "8.63",
              pnl: "-17.26",
              reason: "止损",
            },
            {
              trade_id: "tr_0002",
              kind: "entry",
              time: "2026-11-12T16:00:00Z",
              price: "100",
              side: "buy",
              qty: "1",
            },
          ],
        },
      ),
    );

    expect(geometry.markers).toHaveLength(2);
    expect(geometry.unmatchedMarkers).toBe(1);
    expect(geometry.markers[0]).toMatchObject({
      tradeId: "tr_0001",
      kind: "entry",
      side: "buy",
      x: geometry.candles[0].x,
    });
    expect(geometry.markers[1].label).toContain("盈亏 -17.26");
    for (const marker of geometry.markers) {
      expect(marker.y).toBeGreaterThanOrEqual(geometry.priceTop);
      expect(marker.y).toBeLessThanOrEqual(geometry.priceBottom);
    }
  });
});

describe("formatBeijingTime", () => {
  it("把 UTC 时间换算成北京时间", () => {
    expect(formatBeijingTime("2026-11-12T16:00:00Z")).toBe("2026-11-13 00:00");
    expect(formatBeijingTime("2026-11-12T16:00:00Z", false)).toBe("2026-11-13");
  });
});
