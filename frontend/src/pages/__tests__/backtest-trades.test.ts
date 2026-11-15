import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import type { BacktestTradeRow } from "../../lib/api";
import {
  BacktestTradesView,
  type BacktestTradesViewProps,
} from "../backtests/backtest-trades";

const TRADE: BacktestTradeRow = {
  trade_id: "tr-832",
  product_key: "XAAPL",
  inst_id: "AAPL-USDT-SWAP",
  inst_type: "SWAP",
  side: "long",
  qty: "27.15",
  entry_time: "2026-09-25T16:00:00Z",
  entry_price: "339.783748",
  exit_time: "2026-09-28T16:00:00Z",
  exit_price: "341.165178",
  fee: "18.4877633409",
  slippage: "11.0926755",
  funding: null,
  pnl: "37.5058245",
  net_pnl: "19.0180611591",
  reason: "close",
};

function render(overrides: Partial<BacktestTradesViewProps> = {}): string {
  return renderToStaticMarkup(
    createElement(BacktestTradesView, {
      side: "",
      result: "",
      entryFrom: "",
      entryTo: "",
      onSideChange: () => undefined,
      onResultChange: () => undefined,
      onEntryFromChange: () => undefined,
      onEntryToChange: () => undefined,
      onExport: () => undefined,
      loading: false,
      exporting: false,
      loadError: null,
      exportError: null,
      visible: [TRADE],
      ...overrides,
    }),
  );
}

describe("BacktestTradesView 状态互斥", () => {
  it("有数据时显示表格与当前条数", () => {
    const html = render();

    expect(html).toContain("<table");
    expect(html).toContain("27.15");
    expect(html).toContain("当前筛选后共 1 笔。");
  });

  it("加载中不渲染旧数据，也不写空结果文案", () => {
    const html = render({ loading: true });

    expect(html).toContain("正在读取交易明细…");
    expect(html).not.toContain("<table");
    expect(html).not.toContain("27.15");
    expect(html).not.toContain("没有符合当前筛选条件的交易。");
  });

  it("读取失败时不渲染旧数据，也不写空结果文案", () => {
    const html = render({ loadError: "网络中断" });

    expect(html).toContain("网络中断");
    expect(html).not.toContain("<table");
    expect(html).not.toContain("27.15");
    expect(html).not.toContain("没有符合当前筛选条件的交易。");
    expect(html).toContain("交易明细读取失败。");
  });

  it("读取失败且没有数据时只显示错误", () => {
    const html = render({ loadError: "请求失败（HTTP 502）", visible: [] });

    expect(html).toContain("请求失败（HTTP 502）");
    expect(html).not.toContain("没有符合当前筛选条件的交易。");
  });

  it("导出失败单独提示，已加载的表格继续显示", () => {
    const html = render({ exportError: "CSV 导出失败" });

    expect(html).toContain("CSV 导出失败");
    expect(html).toContain("<table");
    expect(html).toContain("27.15");
  });

  it("没有筛选结果时显示空结果文案", () => {
    const html = render({ visible: [] });

    expect(html).toContain("没有符合当前筛选条件的交易。");
    expect(html).not.toContain("<table");
  });
});
