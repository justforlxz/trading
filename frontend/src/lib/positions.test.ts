import { describe, expect, it } from "vitest";

import {
  accountSourceLabel,
  accountStatusLabel,
  marginModeLabel,
  marginUsageText,
  MISSING_VALUE,
  pnlText,
  positionSideLabel,
  uplRatioText,
  valueOrMissing,
} from "./positions";

describe("持仓展示文案", () => {
  it("缺失值统一显示「未提供」", () => {
    expect(valueOrMissing(null)).toBe(MISSING_VALUE);
    expect(valueOrMissing(undefined)).toBe(MISSING_VALUE);
    expect(valueOrMissing("  ")).toBe(MISSING_VALUE);
    expect(valueOrMissing("1248.60")).toBe("1248.60");
  });

  it("OKX REST 与 WebSocket 来源用不同文字区分", () => {
    expect(accountSourceLabel("okx_rest")).toBe("OKX REST 快照");
    expect(accountSourceLabel("okx_ws")).toBe("OKX WebSocket 推送");
    expect(accountSourceLabel("other_source")).toBe("other_source");
    expect(accountSourceLabel(null)).toBe(MISSING_VALUE);
  });

  it("账户状态、方向与保证金模式使用可读文字", () => {
    expect(accountStatusLabel("ok")).toBe("正常");
    expect(accountStatusLabel("stale")).toBe("快照已过期");
    expect(accountStatusLabel("unconfigured")).toBe("未配置 OKX 密钥");
    expect(positionSideLabel("long")).toBe("多");
    expect(positionSideLabel("short")).toBe("空");
    expect(marginModeLabel("cross")).toBe("全仓");
    expect(marginModeLabel("isolated")).toBe("逐仓");
    expect(marginModeLabel(null)).toBe(MISSING_VALUE);
  });

  it("保证金使用率只补单位，不重新换算", () => {
    expect(marginUsageText("45.36")).toBe("45.36%");
    expect(marginUsageText(null)).toBe(MISSING_VALUE);
  });

  it("盈亏率把契约比率换算成百分数，盈亏值只补正负号", () => {
    expect(uplRatioText("0.0204")).toBe("+2.04%");
    expect(uplRatioText("-0.0204")).toBe("-2.04%");
    expect(uplRatioText(null)).toBe(MISSING_VALUE);
    expect(pnlText("36.96")).toBe("+36.96");
    expect(pnlText("-1.2")).toBe("-1.2");
    expect(pnlText(undefined)).toBe(MISSING_VALUE);
  });
});
