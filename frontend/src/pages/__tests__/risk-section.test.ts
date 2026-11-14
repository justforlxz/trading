import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import type { RiskExposure } from "../../lib/risk";
import {
  RiskSectionView,
  type RiskSectionViewProps,
} from "../positions/risk-section";

const EXPOSURE: RiskExposure = {
  as_of: "2026-11-13T09:00:00Z",
  status: "ok",
  summary: {
    currency: "USDT",
    gross_notional: "4393.20",
    long_notional: "3412.80",
    margin_usage_basis: "margin_ratio",
    margin_usage_pct: "45.36",
    net_notional: "2432.40",
    risk_level: "low",
    short_notional: "980.40",
  },
  positions: [
    {
      atr_distance: "3.8",
      display_symbol: "AAPL-USDT",
      flags: [],
      inst_id: "AAPL-USDT-SWAP",
      lever: "3",
      mark_px: "231.42",
      notional: "1851.36",
      position_ref: "exchange:okx-main:123456",
      side: "long",
      source: "exchange",
      stop_distance_pct: "9.25",
      stop_px: "210.00",
      weight_pct: "42.14",
    },
  ],
  sectors: [
    {
      notional: "1200.00",
      sector: "semiconductor",
      weight_pct: "27.32",
    },
  ],
  rules: [
    {
      level: "warning",
      position_ref: "exchange:okx-main:123456",
      rule_id: "stop_distance",
      threshold: "1",
      value: "0.8",
    },
  ],
};

function render(overrides: Partial<RiskSectionViewProps> = {}): string {
  return renderToStaticMarkup(
    createElement(RiskSectionView, {
      exposure: EXPOSURE,
      loading: false,
      error: null,
      notice: null,
      saveError: null,
      savingRef: null,
      onRefresh: () => undefined,
      onRetry: () => undefined,
      onSaveConfig: () => undefined,
      ...overrides,
    }),
  );
}

describe("RiskSectionView", () => {
  it("组合层在前，依次展示行业、规则和持仓层，数值原样来自后端", () => {
    const html = render();

    const portfolioIndex = html.indexOf("组合风险与敞口");
    const sectorIndex = html.indexOf("行业敞口");
    const rulesIndex = html.indexOf("风险规则结果");
    const positionsIndex = html.indexOf("持仓级风险");
    expect(portfolioIndex).toBeGreaterThanOrEqual(0);
    expect(sectorIndex).toBeGreaterThan(portfolioIndex);
    expect(rulesIndex).toBeGreaterThan(sectorIndex);
    expect(positionsIndex).toBeGreaterThan(rulesIndex);

    expect(html).toContain("3412.80 USDT");
    expect(html).toContain("980.40 USDT");
    expect(html).toContain("2432.40 USDT");
    expect(html).toContain("4393.20 USDT");
    expect(html).toContain("45.36%");
    expect(html).toContain("账户保证金比率");
    expect(html).toContain("semiconductor");
    expect(html).toContain("1200.00 USDT");
    expect(html).toContain("27.32%");
    expect(html).toContain("AAPL-USDT");
    expect(html).toContain("1851.36 USDT");
    expect(html).toContain("42.14%");
    expect(html).toContain("210.00");
    expect(html).toContain("9.25%");
    expect(html).toContain("3.8 ATR");
    expect(html).toContain("OKX 快照");
  });

  it("每条规则展示规则 ID、计算值、阈值和参与计算的字段名", () => {
    const html = render();

    expect(html).toContain("止损距离不足 1 ATR");
    expect(html).toContain("stop_distance");
    expect(html).toContain("0.8");
    expect(html).toContain("mark_px");
    expect(html).toContain("stop_px");
    expect(html).toContain("atr");
    expect(html).toContain("预警");
  });

  it("综合风险等级只跟随后端，不用规则结果在前端重算", () => {
    const low = render({
      exposure: {
        ...EXPOSURE,
        summary: { ...EXPOSURE.summary, risk_level: "low" },
        rules: [
          {
            level: "critical",
            position_ref: null,
            rule_id: "margin_usage",
            threshold: "70",
            value: "95",
          },
        ],
      },
    });
    expect(low).toContain(">低<");
    expect(low).not.toContain(">高<");

    const high = render({
      exposure: {
        ...EXPOSURE,
        summary: { ...EXPOSURE.summary, risk_level: "high" },
        rules: [],
      },
    });
    expect(high).toContain(">高<");
  });

  it("后端字段为空时写不可用和原因，不显示 0", () => {
    const html = render({
      exposure: {
        ...EXPOSURE,
        summary: {
          ...EXPOSURE.summary,
          margin_usage_basis: null,
          margin_usage_pct: null,
        },
        sectors: [],
        positions: [
          {
            ...EXPOSURE.positions[0],
            atr_distance: null,
            flags: ["no_market_data", "atr_unavailable"],
            lever: null,
            mark_px: null,
            notional: null,
            stop_distance_pct: null,
            stop_px: null,
            weight_pct: null,
          },
        ],
      },
    });

    expect(html).toContain("不可用（后端未返回保证金使用率）");
    expect(html).toContain("不可用（缺少标的规格或行情）");
    expect(html).toContain("不可用（没有本地止损配置）");
    expect(html).toContain("不可用（后端未返回杠杆）");
    expect(html).toContain("后端标记：缺少标的规格或行情、缺少 ATR");
    expect(html).not.toContain(">0<");
  });

  it("只缺 ATR 时显示具体原因，不把 ATR 距离写成 0", () => {
    const html = render({
      exposure: {
        ...EXPOSURE,
        positions: [
          {
            ...EXPOSURE.positions[0],
            atr_distance: null,
            flags: ["atr_unavailable"],
          },
        ],
      },
    });

    expect(html).toContain("不可用（缺少 ATR（日线已完成 K 线不足））");
  });

  it("请求失败时显示不可用和原因，不保留上一次数值", () => {
    const html = render({
      exposure: null,
      error: "风险与敞口不可用：请求失败（HTTP 503）",
    });

    expect(html).toContain("风险与敞口不可用：请求失败（HTTP 503）");
    expect(html).toContain("重试");
    expect(html).not.toContain("4393.20");
    expect(html).not.toContain("AAPL-USDT");
  });

  it("规则缺少计算值或阈值时写不可用，不补 0", () => {
    const html = render({
      exposure: {
        ...EXPOSURE,
        rules: [
          {
            level: "warning",
            position_ref: "exchange:okx-main:123456",
            rule_id: "stop_missing",
            threshold: null,
            value: null,
          },
        ],
      },
    });

    expect(html).toContain("不可用（该规则不使用计算值）");
    expect(html).toContain("不可用（该规则不使用阈值）");
    expect(html).toContain("stop_missing");
    expect(html).toContain("stop_px");
  });

  it("非 stop_missing 规则缺少计算值或阈值时指出后端未返回", () => {
    const html = render({
      exposure: {
        ...EXPOSURE,
        rules: [
          {
            level: "warning",
            position_ref: null,
            rule_id: "high_leverage",
            threshold: null,
            value: null,
          },
        ],
      },
    });

    expect(html).toContain("不可用（后端未返回计算值）");
    expect(html).toContain("不可用（后端未返回阈值）");
  });

  it("未知规则仍展示规则 ID，输入字段写不可用", () => {
    const html = render({
      exposure: {
        ...EXPOSURE,
        rules: [
          {
            level: "warning",
            position_ref: null,
            rule_id: "new_rule",
            threshold: "1",
            value: "2",
          },
        ],
      },
    });

    expect(html).toContain("未登记的规则");
    expect(html).toContain("new_rule");
    expect(html).toContain("不可用（前端未登记该规则的输入字段）");
  });

  it("每个持仓提供风险配置表单，字段名与接口契约一致", () => {
    const html = render();

    expect(html).toContain("风险设置");
    expect(html).toContain("止损价 stop_px");
    expect(html).toContain("风险预算 risk_budget");
    expect(html).toContain("预警阈值 warning_threshold_pct");
    expect(html).toContain("保存风险设置");
  });

  it("空持仓显示暂无持仓，不编造风险规则", () => {
    const html = render({
      exposure: {
        ...EXPOSURE,
        positions: [],
        rules: [],
        sectors: [],
        status: "empty",
        summary: {
          ...EXPOSURE.summary,
          gross_notional: "0",
          long_notional: "0",
          net_notional: "0",
          short_notional: "0",
        },
      },
    });

    expect(html).toContain("暂无持仓");
    expect(html).toContain("暂无持仓，没有行业敞口。");
    expect(html).toContain("暂无持仓，没有风险规则结果。");
    expect(html).toContain("暂无持仓。");
  });

  it("保存成功提示展示后端返回的字段；保存失败保留错误", () => {
    const saved = render({
      notice: "已保存 exchange:okx-main:123456 的风险配置：止损价 210.00、风险预算 50。",
    });
    expect(saved).toContain("止损价 210.00");
    expect(saved).toContain("风险预算 50");

    const failed = render({ saveError: "保存风险配置失败：止损价必须是大于 0 的十进制数" });
    expect(failed).toContain("保存风险配置失败");
  });
});
