import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import type { AccountSummary } from "../../lib/positions";
import { PositionsOverviewStripView } from "../positions/overview-strip";

const ACCOUNT: AccountSummary = {
  account_id: "okx-main",
  captured_at: "2026-11-13T09:00:00Z",
  currency: "USDT",
  day_pnl: "-42.10",
  day_pnl_basis: "equity_only",
  position_notional: "6854.20",
  position_notional_at: "2026-11-13T08:30:00Z",
  source: "okx_rest",
  status: "ok",
  unrealized_pnl: "318.42",
};

function render(account: AccountSummary | null, loading = false): string {
  return renderToStaticMarkup(
    createElement(PositionsOverviewStripView, { account, loading }),
  );
}

describe("PositionsOverviewStripView", () => {
  it("概览条展示四项后端数值、来源与快照时间", () => {
    const html = render(ACCOUNT);

    expect(html).toContain("持仓市值");
    expect(html).toContain("6854.20");
    expect(html).toContain("未实现盈亏");
    expect(html).toContain("+318.42");
    expect(html).toContain("今日盈亏");
    expect(html).toContain("-42.10");
    expect(html).toContain("OKX 同步状态");
    expect(html).toContain("正常");
    expect(html).toContain("2026-11-13 17:00");
    expect(html).toContain("OKX REST 快照");
    expect(html).toContain("来源：后端持仓快照 · 截至 2026-11-13 16:30");
    expect(html).toContain("基准 equity_only");
  });

  it("没有账户快照时四项显示未提供，不使用 0 冒充", () => {
    const html = render(null);

    expect(html).toContain("未提供");
    expect(html).toContain("后端未提供持仓市值汇总");
    expect(html).toContain("没有可用的同步状态");
    expect(html).not.toContain(">0<");
  });

  it("持仓市值缺失时明确写后端未提供，今日盈亏缺失时写日初基准未提供", () => {
    const html = render({
      ...ACCOUNT,
      day_pnl: null,
      position_notional: null,
      unrealized_pnl: null,
    });

    expect(html).toContain("后端未提供持仓市值汇总");
    expect(html).toContain("后端未提供日初基准快照");
    expect(html).toContain("未提供");
  });

  it("未配置密钥时显示后端状态，不展示历史数值冒充当前值", () => {
    const html = render({
      account_id: "okx-main",
      currency: "USDT",
      day_pnl_basis: "equity_only",
      status: "unconfigured",
    });

    expect(html).toContain("未配置 OKX 密钥");
    expect(html).toContain("未提供");
  });
});
