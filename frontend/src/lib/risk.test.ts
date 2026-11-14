import { describe, expect, it } from "vitest";

import {
  buildRiskConfigPayload,
  hasRiskConfigInput,
  measureText,
  notionalText,
  percentText,
  riskConfigPath,
  riskExposureProblem,
  riskLevelView,
  riskRuleMeta,
  riskStatusLabel,
  ruleLevelView,
  textOrUnavailable,
} from "./risk";

describe("风险与敞口展示文案", () => {
  it("缺失值写不可用和原因，不写 0", () => {
    expect(percentText(null, "后端未返回保证金使用率")).toBe(
      "不可用（后端未返回保证金使用率）",
    );
    expect(percentText("", "后端未返回单标的占比")).toBe("不可用（后端未返回单标的占比）");
    expect(notionalText(undefined, "USDT")).toBe("不可用（后端未返回名义价值）");
    expect(measureText(null, "ATR", "缺少 ATR")).toBe("不可用（缺少 ATR）");
    expect(textOrUnavailable(" ")).toBe("不可用（后端未返回该字段）");
  });

  it("有值时原样展示，只补单位和币种", () => {
    expect(percentText("45.36")).toBe("45.36%");
    expect(notionalText("3412.80", "USDT")).toBe("3412.80 USDT");
    expect(measureText("3.8", "ATR")).toBe("3.8 ATR");
    expect(textOrUnavailable("210.00")).toBe("210.00");
  });

  it("风险等级与规则级别只认后端枚举，未知值写不可用", () => {
    expect(riskLevelView("low").label).toBe("低");
    expect(riskLevelView("medium").label).toBe("中");
    expect(riskLevelView("high").label).toBe("高");
    expect(riskLevelView("critical").label).toBe("不可用（后端未返回有效风险等级）");
    expect(riskLevelView(null).available).toBe(false);

    expect(ruleLevelView("warning").label).toBe("预警");
    expect(ruleLevelView("critical").label).toBe("严重");
    expect(ruleLevelView("high").label).toBe("不可用（后端未返回规则级别）");
    expect(ruleLevelView(undefined).available).toBe(false);
  });

  it("风险状态和保证金口径使用固定文案", () => {
    expect(riskStatusLabel("ok")).toBe("正常");
    expect(riskStatusLabel("empty")).toBe("暂无持仓");
    expect(riskStatusLabel("stale")).toContain("不可用");
  });
});

describe("风险规则输入字段", () => {
  it("五条后端规则的规则 ID、文案和输入字段都能追溯", () => {
    expect(riskRuleMeta("stop_missing")).toEqual({
      label: "未设置止损",
      inputs: ["stop_px"],
    });
    expect(riskRuleMeta("stop_distance")).toEqual({
      label: "止损距离不足 1 ATR",
      inputs: ["mark_px", "stop_px", "atr"],
    });
    expect(riskRuleMeta("high_leverage")?.inputs).toEqual([
      "lever",
      "settings.risk.max_leverage",
    ]);
    expect(riskRuleMeta("single_instrument_weight")?.inputs).toContain("weight_pct");
    expect(riskRuleMeta("margin_usage")?.inputs).toContain("margin_usage_pct");
  });

  it("未知规则不补造输入字段", () => {
    expect(riskRuleMeta("new_rule")).toBeNull();
  });
});

describe("风险配置请求构造", () => {
  it("只提交填写了的字段，并去掉首尾空白", () => {
    expect(
      buildRiskConfigPayload({
        stopPx: " 210.00 ",
        riskBudget: "",
        warningThresholdPct: "1.5",
      }),
    ).toEqual({ stop_px: "210.00", warning_threshold_pct: "1.5" });
  });

  it("全部留空时不产生请求体", () => {
    const fields = { stopPx: " ", riskBudget: "", warningThresholdPct: "  " };
    expect(buildRiskConfigPayload(fields)).toEqual({});
    expect(hasRiskConfigInput(fields)).toBe(false);
  });

  it("持仓引用在路径里编码，冒号不直接出现在路径段", () => {
    expect(riskConfigPath("exchange:okx-main:123456")).toBe(
      "/positions/exchange%3Aokx-main%3A123456/risk-config",
    );
    expect(riskConfigPath("manual:abc")).toBe("/positions/manual%3Aabc/risk-config");
  });
});

describe("风险响应结构检查", () => {
  const valid = {
    as_of: "2026-11-13T09:00:00Z",
    status: "ok",
    summary: {},
    positions: [],
    sectors: [],
    rules: [],
  };

  it("完整结构通过检查", () => {
    expect(riskExposureProblem(valid)).toBeNull();
  });

  it("缺少 summary、数组或状态异常时指出具体原因", () => {
    expect(riskExposureProblem({ ...valid, summary: null })).toBe("后端返回缺少 summary");
    expect(riskExposureProblem({ ...valid, positions: null })).toBe("后端返回缺少 positions");
    expect(riskExposureProblem({ ...valid, sectors: {} })).toBe("后端返回缺少 sectors");
    expect(riskExposureProblem({ ...valid, rules: null })).toBe("后端返回缺少 rules");
    expect(riskExposureProblem({ ...valid, as_of: "" })).toBe("后端返回缺少 as_of");
    expect(riskExposureProblem({ ...valid, status: "stale" })).toBe(
      "后端返回的 status 不是 ok 或 empty",
    );
    expect(riskExposureProblem(null)).toBe("后端未返回风险与敞口数据");
  });
});
