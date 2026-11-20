import { describe, expect, it } from "vitest";

import {
  coverageText,
  dataTimeText,
  groupCounts,
  matchesGroup,
  metricText,
  ratioPercent,
  shortUtc,
  trendLabel,
  trendText,
  watchlistGroups,
} from "./watchlist";

/** 分组筛选只读条目自己的 `group`，其余字段不参与，这里用最小形状即可。 */
type GroupedItem = { group: string };

describe("分组筛选", () => {
  const items: GroupedItem[] = [{ group: "美股" }, { group: "加密" }, { group: "美股" }];

  it("全部不过滤，选中分组只留该组标的", () => {
    expect(items.filter((item) => matchesGroup(item, null))).toHaveLength(3);
    expect(items.filter((item) => matchesGroup(item, "美股"))).toHaveLength(2);
    expect(items.filter((item) => matchesGroup(item, "加密"))).toHaveLength(1);
    expect(items.filter((item) => matchesGroup(item, "默认"))).toHaveLength(0);
  });

  it("分组名来自接口 groups 与条目自身的 group，去重并保留首次出现顺序", () => {
    expect(watchlistGroups(items, ["加密", "默认"])).toEqual(["加密", "默认", "美股"]);
    expect(watchlistGroups(items, ["美股", "加密"])).toEqual(["美股", "加密"]);
    expect(watchlistGroups([], [])).toEqual([]);
  });

  it("空白分组名不算一个分组", () => {
    expect(watchlistGroups([{ group: "  " }], [" "])).toEqual([]);
  });

  it("计数覆盖接口列出的空分组，各分组之和等于全部", () => {
    const counts = groupCounts(items, ["美股", "加密", "默认"]);

    expect(counts).toEqual({ 美股: 2, 加密: 1, 默认: 0 });
    expect(Object.values(counts).reduce((sum, count) => sum + count, 0)).toBe(items.length);
  });
});

describe("缺数据文案", () => {
  it("没有 K 线写尚未同步，有 K 线但指标不足写未生成", () => {
    expect(metricText(null, "missing")).toBe("尚未同步");
    expect(metricText(null, "partial")).toBe("未生成");
    expect(metricText("61.4", "ok")).toBe("61.4");
    expect(trendText(null, "missing")).toBe("尚未同步");
    expect(trendText(null, "partial")).toBe("未生成");
  });

  it("趋势枚举翻译为中文，未知值也不编造方向", () => {
    expect(trendLabel("bullish")).toBe("偏多");
    expect(trendLabel("bearish")).toBe("偏空");
    expect(trendLabel("neutral")).toBe("中性");
    expect(trendLabel(null)).toBe("未生成");
  });

  it("K 线覆盖与数据时间不把空值写成 0", () => {
    expect(coverageText({ candle_count: 0, data_status: "missing" })).toBe("尚未同步");
    expect(coverageText({ candle_count: 3, data_status: "partial" })).toBe(
      "日线 3 根 · 指标待补",
    );
    expect(coverageText({ candle_count: 846, data_status: "ok" })).toBe("日线 846 根");
    expect(dataTimeText(null)).toBe("尚未同步");
    expect(dataTimeText("2026-11-12T16:00:00Z")).toBe("最新日线 11-12 16:00 UTC");
    expect(shortUtc("2026-11-12T16:00:00Z")).toBe("11-12 16:00 UTC");
  });
});

describe("市场环境比率", () => {
  it("只做百分比换算，空值写未生成", () => {
    expect(ratioPercent("0.62")).toBe("62%");
    expect(ratioPercent(null)).toBe("未生成");
  });
});
