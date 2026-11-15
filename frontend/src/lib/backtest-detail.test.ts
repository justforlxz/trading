import { describe, expect, it } from "vitest";

import type {
  BacktestChartResponse,
  BacktestEquityPoint,
  BacktestReplayPoint,
  BacktestTradeRow,
} from "./api";
import {
  backtestChartInput,
  chartMarkerCounts,
  drawdownLinePoints,
  equityLinePoints,
  filterCsvByEntryDate,
  filterTradesByEntryDate,
  ratioToPercent,
  replayClosePoints,
} from "./backtest-detail";

function trade(entryTime: string, exitTime = "2026-11-10T00:00:00Z"): BacktestTradeRow {
  return {
    trade_id: `tr-${entryTime}`,
    product_key: "XAAPL",
    inst_id: "AAPL-USDT-SWAP",
    inst_type: "SWAP",
    side: "long",
    qty: "1",
    entry_time: entryTime,
    entry_price: "100",
    exit_time: exitTime,
    exit_price: "101",
    fee: "0.1",
    slippage: "0.05",
    funding: null,
    pnl: "1",
    net_pnl: "0.9",
    reason: "测试",
  };
}

describe("ratioToPercent", () => {
  it("把后端比值改写成百分比文案", () => {
    expect(ratioToPercent("0.54")).toBe("54.00%");
    expect(ratioToPercent("-0.006")).toBe("-0.60%");
  });

  it("缺失值写破折号，非数字原样返回", () => {
    expect(ratioToPercent(null)).toBe("—");
    expect(ratioToPercent("n/a")).toBe("n/a");
  });
});

describe("backtestChartInput", () => {
  it("保留 K 线、均线与标记，缺口为空", () => {
    const chart: BacktestChartResponse = {
      run_id: "bt_0001",
      inst_id: "AAPL-USDT-SWAP",
      bar: "1d",
      data_source: "okx_swap",
      candles: [
        {
          time: "2026-11-05T00:00:00Z",
          open: "100",
          high: "104",
          low: "99",
          close: "103",
          volume: "1200",
          is_complete: true,
          source: "okx_swap",
        },
      ],
      markers: [
        {
          trade_id: "tr_0001",
          kind: "entry",
          time: "2026-11-05T00:00:00Z",
          price: "101",
          side: "buy",
          qty: "8",
        },
      ],
      overlays: [],
    };

    const input = backtestChartInput(chart);
    expect(input.candles[0].open_time).toBe("2026-11-05T00:00:00Z");
    expect(input.gaps).toEqual([]);
    expect(input.markers).toHaveLength(1);
    expect(chartMarkerCounts(chart)).toEqual({ entries: 1, exits: 0, unmatched: 0 });
    expect(
      chartMarkerCounts({ ...chart, markers: [{ ...chart.markers[0], time: "2026-11-06T00:00:00Z" }] }),
    ).toEqual({ entries: 0, exits: 0, unmatched: 1 });
  });
});

describe("净值与回撤序列", () => {
  const points: BacktestEquityPoint[] = [
    { time: "2026-11-05T00:00:00Z", equity: "10000", benchmark_equity: null, drawdown: "0" },
    { time: "2026-11-06T00:00:00Z", equity: "9940", benchmark_equity: null, drawdown: "-0.006" },
  ];

  it("净值原样保留，回撤改成百分比", () => {
    expect(equityLinePoints(points)).toEqual([
      { time: "2026-11-05T00:00:00Z", price: "10000" },
      { time: "2026-11-06T00:00:00Z", price: "9940" },
    ]);
    expect(drawdownLinePoints(points)).toEqual([
      { time: "2026-11-05T00:00:00Z", price: "0.0000" },
      { time: "2026-11-06T00:00:00Z", price: "-0.6000" },
    ]);
  });
});

describe("replayClosePoints", () => {
  const points: BacktestReplayPoint[] = [
    {
      index: 0,
      time: "2026-11-05T00:00:00Z",
      close: "103",
      equity: "10000",
      cash: "10000",
      position: "0",
      signal: "HOLD",
      indicators: { ma20: "98.4", ma60: null },
    },
    {
      index: 1,
      time: "2026-11-06T00:00:00Z",
      close: null,
      equity: "10020",
      cash: "9128",
      position: "891",
      signal: "BUY",
      indicators: {},
    },
    {
      index: 2,
      time: "2026-11-07T00:00:00Z",
      close: "101",
      equity: "10030",
      cash: "9128",
      position: "901",
      signal: "HOLD",
      indicators: {},
    },
  ];

  it("只取当前帧之前的收盘价，缺失值不补造", () => {
    expect(replayClosePoints(points, 0)).toEqual([
      { time: "2026-11-05T00:00:00Z", price: "103" },
    ]);
    expect(replayClosePoints(points, 1)).toHaveLength(1);
    expect(replayClosePoints(points, 2)).toHaveLength(2);
  });
});

describe("交易按建仓日期筛选", () => {
  const trades = [
    trade("2026-11-06T00:00:00Z"),
    trade("2026-11-08T12:00:00Z"),
    trade("2026-11-10T00:00:00Z"),
  ];

  it("没有条件时原样返回", () => {
    expect(filterTradesByEntryDate(trades, "", "")).toBe(trades);
  });

  it("按 UTC 日期边界筛选，包含起止日", () => {
    expect(filterTradesByEntryDate(trades, "2026-11-07", "2026-11-09")).toEqual([trades[1]]);
    expect(filterTradesByEntryDate(trades, "2026-11-08", "")).toEqual([trades[1], trades[2]]);
    expect(filterTradesByEntryDate(trades, "", "2026-11-06")).toEqual([trades[0]]);
  });
});

describe("CSV 按建仓日期裁剪", () => {
  const csv =
    "\ufeff标的,方向,开仓时间,开仓价,平仓时间,平仓价,数量,手续费,资金费,滑点,净盈亏,退出原因\r\n" +
    "AAPL-USDT-SWAP,多头,2026-11-06T00:00:00Z,101,2026-11-08T00:00:00Z,103,8.63,0.87,,0.44,16.39,MA20 下穿\r\n" +
    "AAPL-USDT-SWAP,多头,2026-11-09T00:00:00Z,103,2026-11-10T00:00:00Z,102,8.63,0.87,,0.44,-8.00,\"止损, 保护\"\r\n";

  it("没有日期条件时原文返回", () => {
    expect(filterCsvByEntryDate(csv, "", "")).toBe(csv);
  });

  it("只保留落在日期区间内的行，并保留原始单元格文本", () => {
    const filtered = filterCsvByEntryDate(csv, "2026-11-09", "2026-11-09");
    expect(filtered).not.toContain("\r\r\n");
    const rows = filtered.trimEnd().split("\r\n");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toContain("开仓时间");
    expect(rows[1]).toContain('"止损, 保护"');
    expect(rows[1]).not.toContain("2026-11-06");
  });
});
