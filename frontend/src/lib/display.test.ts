import { describe, expect, it } from "vitest";

import { percentValue } from "./display";

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
