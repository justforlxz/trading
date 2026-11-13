import { describe, expect, it } from "vitest";

import { percentValue, priceChangeValue } from "./display";

describe("percentValue", () => {
  it("把比率换算成百分比并补正号", () => {
    expect(percentValue("0.05")).toBe("+5%");
    expect(percentValue("0.1234")).toBe("+12.34%");
    expect(percentValue("0")).toBe("+0%");
  });

  it("负数沿用负号，不补正号", () => {
    expect(percentValue("-0.025")).toBe("-2.5%");
  });
});

describe("priceChangeValue", () => {
  it("普通价格保留两位小数", () => {
    expect(priceChangeValue("4.76", "358.57")).toBe("+4.76");
    expect(priceChangeValue("-2.5", "358.57")).toBe("-2.50");
  });

  it("低价标的按价格精度显示，不变成 +0.00", () => {
    expect(priceChangeValue("0.000012", "0.00001234")).toBe("+0.000012");
    expect(priceChangeValue("-0.000001", "0.00001234")).toBe("-0.000001");
  });
});
