import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import type { AccountSummary, ExchangePositions } from "../../lib/positions";
import { OkxSectionView, type OkxSectionViewProps } from "../positions/okx-section";

const UNCONFIGURED_ACCOUNT: AccountSummary = {
  account_id: "okx-main",
  currency: "USDT",
  day_pnl_basis: "equity_only",
  status: "unconfigured",
};

const UNCONFIGURED_POSITIONS: ExchangePositions = {
  items: [],
  status: "unconfigured",
};

const OK_ACCOUNT: AccountSummary = {
  account_id: "okx-main",
  available_equity: "682.30",
  available_margin: "682.30",
  captured_at: "2026-11-13T09:00:00Z",
  cash_balance: "0",
  currency: "USDT",
  day_pnl: "12.30",
  day_pnl_basis: "equity_only",
  equity: "1248.60",
  margin_usage_pct: "45.36",
  source: "okx_rest",
  status: "ok",
  unrealized_pnl: "31.84",
  used_margin: "566.30",
};

const OK_POSITIONS: ExchangePositions = {
  as_of: "2026-11-13T09:00:00Z",
  items: [
    {
      asset_class: "tokenized_equity",
      avg_px: "226.80",
      display_symbol: "AAPL-USDT",
      inst_id: "AAPL-USDT-SWAP",
      lever: "3",
      liq_px: "151.20",
      margin: "604.80",
      mark_px: "231.42",
      mgn_mode: "cross",
      name: "AAPL",
      pos_id: "123456",
      pos_side: "long",
      size: "8",
      upl: "36.96",
      upl_ratio: "0.0204",
    },
  ],
  status: "ok",
};

function render(overrides: Partial<OkxSectionViewProps> = {}): string {
  return renderToStaticMarkup(
    createElement(OkxSectionView, {
      account: OK_ACCOUNT,
      positions: OK_POSITIONS,
      loading: false,
      error: null,
      syncError: null,
      syncing: false,
      liveness: "live",
      onSync: () => undefined,
      onRetry: () => undefined,
      ...overrides,
    }),
  );
}

describe("OkxSectionView", () => {
  it("正常快照展示账户数值、时间、来源与持仓列", () => {
    const html = render();

    expect(html).toContain("1248.60");
    expect(html).toContain("682.30");
    expect(html).toContain("566.30");
    expect(html).toContain("45.36%");
    expect(html).toContain("+31.84");
    expect(html).toContain("+12.30");
    expect(html).toContain("equity_only");
    expect(html).toContain("2026-11-13 17:00");
    expect(html).toContain("OKX REST 快照");
    expect(html).toContain("AAPL-USDT");
    expect(html).toContain("AAPL");
    expect(html).toContain("多");
    expect(html).toContain("全仓");
    expect(html).toContain("+2.04%");
    expect(html).toContain("截至");
  });

  it("未配置密钥时显示明确提示，不用 0 或演示数值冒充", () => {
    const html = render({
      account: UNCONFIGURED_ACCOUNT,
      positions: UNCONFIGURED_POSITIONS,
    });

    expect(html).toContain("未配置 OKX 密钥");
    expect(html).toContain("未提供");
    expect(html).not.toContain(">0<");
    expect(html).not.toContain("1248.60");
  });

  it("快照过期时显示状态与最近快照时间", () => {
    const html = render({ account: { ...OK_ACCOUNT, status: "stale" } });

    expect(html).toContain("快照已过期");
    expect(html).toContain("2026-11-13 17:00");
  });

  it("空持仓显示「暂无持仓」，缺失字段显示「未提供」", () => {
    const empty = render({ positions: { items: [], status: "ok" } });
    expect(empty).toContain("暂无持仓");

    const missing = render({
      positions: {
        as_of: "2026-11-13T09:00:00Z",
        items: [{ ...OK_POSITIONS.items[0], mark_px: null, upl: null, upl_ratio: null, lever: null, liq_px: null, margin: null }],
        status: "ok",
      },
    });
    expect(missing).toContain("未提供");
  });

  it("请求失败显示错误与重试入口", () => {
    const html = render({
      account: null,
      positions: null,
      error: "无法连接后端服务",
    });

    expect(html).toContain("无法连接后端服务");
    expect(html).toContain("重试");
  });

  it("同步失败时保留上一次快照并显示错误", () => {
    const html = render({ syncError: "同步失败，仍显示上一次快照：HTTP 502" });

    expect(html).toContain("同步失败，仍显示上一次快照");
    expect(html).toContain("1248.60");
    expect(html).toContain("2026-11-13 17:00");
  });

  it("推送断开时标注已断开，并保留最后已知价格", () => {
    const html = render({ liveness: "stale" });

    expect(html).toContain("实时推送已断开");
    expect(html).toContain("已断开");
    expect(html).toContain("231.42");
  });

  it("OKX 区只读，没有下单、撤单、改单或平仓入口", () => {
    const html = render();

    for (const forbidden of ["下单", "撤单", "改单", "平仓"]) {
      expect(html).not.toContain(forbidden);
    }
  });
});
