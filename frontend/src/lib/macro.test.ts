import { describe, expect, it } from "vitest";

import type { MacroOverviewResponse, MacroReading } from "./api";
import {
  changeText,
  delayLabel,
  macroQualityLabel,
  macroStaleNotice,
  primaryReading,
  readingOf,
  readingValueText,
  regimeLabel,
  regimeTone,
  spreadTone,
  spreadUnavailableText,
  spreadValueText,
  vixReading,
} from "./macro";

function reading(overrides: Partial<MacroReading> = {}): MacroReading {
  return {
    series_id: "us10y",
    name: "美国 10 年期国债",
    unit: "%",
    granularity: "minute",
    provider: "yahoo",
    source_url: null,
    value: "4.92",
    change: "-0.13",
    as_of: "2026-11-20T20:59:00Z",
    is_delayed: true,
    market_session: "open",
    quality_status: "normal",
    regime: null,
    error: null,
    ...overrides,
  };
}

function overview(overrides: Partial<MacroOverviewResponse> = {}): MacroOverviewResponse {
  return {
    as_of: "2026-11-22T07:01:00Z",
    stale: false,
    stale_reason: null,
    readings: [
      reading(),
      reading({ granularity: "daily", provider: "treasury", value: "4.91", is_delayed: false }),
      reading({ series_id: "us2y", name: "美国 2 年期国债", granularity: "daily", value: "4.63" }),
      reading({
        series_id: "vix",
        name: "恐慌指数 VIX",
        unit: "点",
        value: "35.89",
        change: "7.45",
        regime: "panic",
      }),
    ],
    spread: {
      available: true,
      value_bp: "29",
      inverted: false,
      trading_day: "2026-11-20",
      quality_status: "normal",
      reason: null,
      sources: [{ provider: "treasury", source_url: null }],
    },
    ...overrides,
  };
}

describe("宏观读数展示", () => {
  it("按序列与粒度取行；没有这一行时给 null", () => {
    const data = overview();

    expect(readingOf(data, "us10y", "minute")?.provider).toBe("yahoo");
    expect(readingOf(data, "us10y", "daily")?.provider).toBe("treasury");
    expect(readingOf(data, "us30y", "daily")).toBeNull();
  });

  it("优先分钟级；分钟级缺值时才退回日结值", () => {
    const data = overview();
    expect(primaryReading(data, "us10y")?.granularity).toBe("minute");

    const withoutMinute = overview({
      readings: [
        reading({ value: null, error: "尚未同步" }),
        reading({ granularity: "daily", provider: "treasury", value: "4.91" }),
      ],
    });
    expect(primaryReading(withoutMinute, "us10y")?.granularity).toBe("daily");
  });

  it("关注列表只取 VIX 一条", () => {
    expect(vixReading(overview())?.series_id).toBe("vix");
    expect(vixReading(null)).toBeNull();
  });

  it("数值与单位直接拼接，没有值时给 null", () => {
    expect(readingValueText(reading())).toBe("4.92%");
    expect(readingValueText(reading({ value: null }))).toBeNull();
    expect(readingValueText(null)).toBeNull();
  });

  it("日变化带符号；缺失时给 null", () => {
    expect(changeText(reading())).toBe("-0.13%");
    expect(changeText(reading({ change: "0.2" }))).toBe("+0.2%");
    expect(changeText(reading({ change: null }))).toBeNull();
  });

  it("VIX 分级用后端给的 regime，边界值原样映射", () => {
    expect(regimeLabel("low")).toBe("低波");
    expect(regimeLabel("normal")).toBe("常态");
    expect(regimeLabel("elevated")).toBe("偏高");
    expect(regimeLabel("panic")).toBe("恐慌");
    expect(regimeLabel(null)).toBe("未分级");
    expect(regimeTone("panic")).toContain("rose");
  });

  it("质量与延迟标记只转述后端字段", () => {
    expect(macroQualityLabel("missing")).toBe("缺失");
    expect(macroQualityLabel("stale")).toBe("过期");
    expect(delayLabel(reading({ is_delayed: true }))).toBe("延迟");
    expect(delayLabel(reading({ is_delayed: false }))).toBe("实时");
  });

  it("利差带上正负号；倒挂用红色；不可用时给原因", () => {
    expect(spreadValueText(overview().spread)).toBe("+29bp");
    expect(
      spreadValueText({
        available: true,
        value_bp: "-53",
        inverted: true,
        trading_day: "2026-11-20",
        quality_status: "normal",
        reason: null,
        sources: [],
      }),
    ).toBe("-53bp");
    expect(
      spreadTone({
        available: true,
        value_bp: "-53",
        inverted: true,
        trading_day: "2026-11-20",
        quality_status: "normal",
        reason: null,
        sources: [],
      }),
    ).toContain("rose");
    expect(spreadUnavailableText(overview().spread)).toBeNull();
    expect(
      spreadUnavailableText({
        available: false,
        value_bp: null,
        inverted: false,
        trading_day: null,
        quality_status: "missing",
        reason: "缺少 2Y 的日线结算值",
        sources: [],
      }),
    ).toBe("缺少 2Y 的日线结算值");
  });

  it("总览过期时给出可读提示；未过期时为 null", () => {
    expect(macroStaleNotice(overview())).toBeNull();
    expect(macroStaleNotice(overview({ stale: true, stale_reason: "上游 503" }))).toContain(
      "上游 503",
    );
    expect(macroStaleNotice(overview({ stale: true, stale_reason: null }))).toContain("不能当作实时值");
  });
});
