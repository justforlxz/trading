import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import type { ManualPosition, ManualTrade } from "../../lib/manual-positions";
import {
  ManualSectionView,
  type ManualSectionViewProps,
} from "../positions/manual-section";

const OPEN_POSITION: ManualPosition = {
  asset_class: "tokenized_equity",
  avg_cost: "226.80",
  created_at: "2026-11-13T09:00:00Z",
  display_symbol: "AAPL-USDT",
  id: "position-open",
  inst_id: "AAPL-USDT-SWAP",
  leverage: "3",
  market_value: "1851.36",
  name: "AAPL",
  note: "手动记账",
  price: "231.42",
  price_source: "okx_swap",
  price_status: "ok",
  quantity: "8",
  side: "long",
  status: "open",
  stop_px: "200.00",
  unrealized_pnl: "36.96",
  updated_at: "2026-11-13T09:00:00Z",
};

const CLOSED_POSITION: ManualPosition = {
  asset_class: "crypto",
  avg_cost: "60000",
  created_at: "2026-11-12T09:00:00Z",
  display_symbol: "BTC-USDT",
  id: "position-closed",
  inst_id: "BTC-USDT",
  name: "BTC",
  price_status: "unavailable",
  quantity: "0",
  side: "short",
  status: "closed",
  updated_at: "2026-11-13T10:00:00Z",
};

const TRADES: ManualTrade[] = [
  {
    action: "reduce",
    created_at: "2026-11-13T10:00:00Z",
    fee: "0.10",
    id: "trade-2",
    note: "部分卖出",
    occurred_at: "2026-11-13T10:00:00Z",
    position_avg_cost_after: "226.80",
    position_id: "position-open",
    position_quantity_after: "5",
    position_status_after: "open",
    price: "240.00",
    quantity: "3",
    realized_pnl: "39.50",
  },
  {
    action: "open",
    created_at: "2026-11-13T09:00:00Z",
    fee: "0",
    id: "trade-1",
    occurred_at: "2026-11-13T09:00:00Z",
    position_avg_cost_after: "226.80",
    position_id: "position-open",
    position_quantity_after: "8",
    position_status_after: "open",
    price: "226.80",
    quantity: "8",
  },
];

function view(overrides: Partial<ManualSectionViewProps> = {}): string {
  return renderToStaticMarkup(
    createElement(ManualSectionView, {
      positions: [OPEN_POSITION, CLOSED_POSITION],
      loading: false,
      error: null,
      notice: null,
      filter: "open",
      onFilterChange: () => undefined,
      onRetry: () => undefined,
      onCreate: () => undefined,
      onTrade: () => undefined,
      onEdit: () => undefined,
      onDelete: () => undefined,
      onSelectTrades: () => undefined,
      selectedPosition: null,
      trades: null,
      tradesLoading: false,
      tradesError: null,
      onCloseTrades: () => undefined,
      lastTrade: null,
      lastTradeDuplicate: false,
      onDismissTrade: () => undefined,
      ...overrides,
    }),
  );
}

describe("ManualSectionView", () => {
  it("默认只展示持仓中的手动持仓，并列出契约字段", () => {
    const html = view();

    expect(html).toContain("持仓中 1");
    expect(html).toContain("已平仓 1");
    expect(html).toContain("AAPL-USDT");
    expect(html).toContain("AAPL-USDT-SWAP");
    expect(html).toContain("226.80");
    expect(html).toContain("200.00");
    expect(html).toContain("231.42");
    expect(html).toContain("1851.36");
    expect(html).toContain("+36.96");
    expect(html).toContain("OKX 永续");
    expect(html).not.toContain("BTC-USDT");
  });

  it("切换到已平仓时展示平仓记录，没有行情不显示 0 或相似价格", () => {
    const html = view({ filter: "closed" });

    expect(html).toContain("BTC-USDT");
    expect(html).toContain("已平仓");
    expect(html).toContain("无行情源");
    expect((html.match(/无行情源/gu) ?? []).length).toBeGreaterThanOrEqual(3);
    expect(html).not.toContain("AAPL-USDT");
  });

  it("没有手动持仓时显示空态和创建入口", () => {
    const html = view({ positions: [] });

    expect(html).toContain("还没有手动持仓");
    expect(html).toContain("创建手动持仓");
  });

  it("读取失败时显示后端错误并可重试", () => {
    const html = view({ positions: null, error: "数据库暂时不可用" });

    expect(html).toContain("数据库暂时不可用");
    expect(html).toContain("重试");
  });

  it("选中持仓后展示流水字段，已实现盈亏补正号", () => {
    const html = view({
      selectedPosition: OPEN_POSITION,
      trades: TRADES,
    });

    expect(html).toContain("流水 · AAPL-USDT");
    expect(html).toContain("减仓");
    expect(html).toContain("开仓");
    expect(html).toContain("部分卖出");
    expect(html).toContain("+39.50");
    expect(html).toContain("操作后数量");
    expect(html).toContain("操作后成本");
    expect(html).toContain("更正流水的“价格”列");
  });

  it("没有流水时显示暂无流水", () => {
    const html = view({ selectedPosition: OPEN_POSITION, trades: [] });

    expect(html).toContain("暂无流水");
  });

  it("切换到另一持仓时不展示上一持仓的流水", () => {
    const staleTrades: ManualTrade[] = TRADES.map((trade) => ({
      ...trade,
      id: `stale-${trade.id}`,
      note: "上一本账本",
      position_id: "position-closed",
    }));

    const html = view({
      selectedPosition: OPEN_POSITION,
      trades: staleTrades,
    });

    expect(html).toContain("流水 · AAPL-USDT");
    expect(html).toContain("暂无流水");
    expect(html).not.toContain("上一本账本");
    expect(html).not.toContain("+39.50");
  });

  it("最近一次流水展示后端返回的盈亏、操作后数量与成本", () => {
    const html = view({
      lastTrade: TRADES[0],
      lastTradeDuplicate: true,
    });

    expect(html).toContain("最近一次流水");
    expect(html).toContain("+39.50");
    expect(html).toContain("操作后数量");
    expect(html).toContain("操作后成本");
    expect(html).toContain("该幂等键已有记录，没有重复入账");
  });
});
