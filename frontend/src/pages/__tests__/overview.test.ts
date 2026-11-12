import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import type { OverviewResponse } from "../../lib/api";
import { OverviewView } from "../overview";

const EMPTY_OVERVIEW: OverviewResponse = {
  as_of: "2026-11-10T08:00:00Z",
  market_states: [],
  market: [],
  portfolio: {
    gross_exposure: "0",
    net_exposure: "0",
    open_positions: 0,
    strategies: [],
  },
  recent_opportunities: [],
  risk_events: [],
};

const POPULATED_OVERVIEW: OverviewResponse = {
  as_of: "2026-11-10T08:00:00Z",
  market_states: [
    { inst_type: "SPOT", session: "regular", primary_source: "okx_spot" },
    { inst_type: "SWAP", session: "post", primary_source: "us_equity_proxy" },
  ],
  market: [
    {
      inst_type: "SPOT",
      bar: "1d",
      as_of: "2026-11-10T08:00:00Z",
      breadth: { advancers: 8, decliners: 2, unchanged: 1, ratio: "4", participants: 11 },
      resonance: { strength: "0.62", participants: 11, window: 20 },
    },
    {
      inst_type: "SWAP",
      bar: "1d",
      as_of: "2026-11-10T08:00:00Z",
      breadth: { advancers: 5, decliners: 5, unchanged: 0, ratio: "1", participants: 10 },
      resonance: { strength: "0", participants: 10, window: 20 },
    },
  ],
  portfolio: {
    gross_exposure: "3510.40",
    net_exposure: "1997.15",
    open_positions: 1,
    strategies: [
      {
        instance_id: "si_0001",
        name: "AAPL 均线趋势",
        open_positions: 1,
      },
    ],
  },
  recent_opportunities: [
    {
      opportunity_id: "opp_0001",
      mode: "target",
      anchor_product_key: "AAPL",
      as_of: "2026-11-10T00:00:00Z",
      score: "0.78",
      legs: [
        {
          inst_id: "MSFT-USDT-SWAP",
          inst_type: "SWAP",
          product_key: "MSFT",
          direction: "long",
          score: "0.82",
        },
      ],
      evidence: '{"correlation":0.87}',
      status: "new",
    },
  ],
  risk_events: [
    {
      event_id: "re_0001",
      instance_id: "si_0001",
      inst_id: "AAPL-USDT-SWAP",
      rule: "max_leverage",
      detail: "杠杆 25 超过上限 20",
      created_at: "2026-11-10T07:00:00Z",
      resolved_at: null,
    },
  ],
};

function render(data: OverviewResponse): string {
  return renderToStaticMarkup(createElement(OverviewView, { data }));
}

describe("OverviewView", () => {
  it("空数据时五个区块都显示「暂无」而不是抛错", () => {
    const html = render(EMPTY_OVERVIEW);

    expect(html).toContain("暂无市场状态");
    expect(html).toContain("暂无共振数据");
    expect(html).toContain("暂无策略组合");
    expect(html).toContain("暂无机会");
    expect(html).toContain("暂无风险告警");
  });

  it("有数据时渲染市场状态、共振、组合、机会与告警", () => {
    const html = render(POPULATED_OVERVIEW);

    expect(html).toContain("SPOT 现货");
    expect(html).toContain("交易中");
    expect(html).toContain("OKX 现货行情");
    expect(html).toContain("62%");
    expect(html).toContain("8 涨 / 2 跌 / 1 平");
    expect(html).toContain("AAPL 均线趋势");
    expect(html).toContain("1 个持仓");
    expect(html).toContain("新发现");
    expect(html).toContain("最近机会分数走势");
    expect(html).toContain("max_leverage");
    expect(html).toContain("未处置");
  });
});
