import { describe, expect, it, vi } from "vitest";

import type { CandleBar } from "./api";
import {
  DEFAULT_BAR_ORDER,
  coverageLabel,
  resolveAvailableBar,
  resolveDefaultBar,
} from "./instrument";

function loaderWithData(barsWithData: CandleBar[]) {
  return vi.fn(async (bar: CandleBar) => ({
    candles: barsWithData.includes(bar) ? [{ open_time: "2026-11-10T00:00:00Z" }] : [],
  }));
}

describe("resolveDefaultBar", () => {
  it("优先选择 1d，即使其他周期也有数据", async () => {
    const load = loaderWithData(["1d", "1h"]);

    await expect(resolveDefaultBar(load)).resolves.toBe("1d");
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("1d 没有数据时按顺序找到下一个有数据的周期", async () => {
    const load = loaderWithData(["1h"]);

    await expect(resolveDefaultBar(load)).resolves.toBe("1h");
    expect(load.mock.calls.map(([bar]) => bar)).toEqual(["1d", "4h", "1h"]);
  });

  it("所有周期都没有数据时回到 1d", async () => {
    const load = loaderWithData([]);

    await expect(resolveDefaultBar(load)).resolves.toBe("1d");
    expect(load).toHaveBeenCalledTimes(DEFAULT_BAR_ORDER.length);
  });
});

describe("coverageLabel", () => {
  it("按 UTC 显示起止时刻", () => {
    expect(coverageLabel("2026-07-15T16:00:00Z", "2026-11-11T16:00:00Z")).toBe(
      "2026-07-15 16:00 至 2026-11-11 16:00",
    );
  });

  it("任一端缺失或无法解析时不显示区间", () => {
    expect(coverageLabel(null, "2026-11-11T16:00:00Z")).toBeNull();
    expect(coverageLabel("2026-07-15T16:00:00Z", undefined)).toBeNull();
    expect(coverageLabel("not-a-time", "2026-11-11T16:00:00Z")).toBeNull();
  });
});

describe("resolveAvailableBar", () => {
  it("当前周期可用时保持不变", () => {
    expect(
      resolveAvailableBar(
        [
          { bar: "1d", available: true },
          { bar: "4h", available: true },
        ],
        "4h",
      ),
    ).toBe("4h");
  });

  it("当前周期不可用时退回第一个可用周期", () => {
    expect(
      resolveAvailableBar(
        [
          { bar: "1d", available: true },
          { bar: "4h", available: false },
          { bar: "1h", available: true },
        ],
        "4h",
      ),
    ).toBe("1d");
  });

  it("所有周期都不可用时保持当前选择", () => {
    expect(
      resolveAvailableBar(
        [
          { bar: "1d", available: false },
          { bar: "4h", available: false },
        ],
        "4h",
      ),
    ).toBe("4h");
  });
});
