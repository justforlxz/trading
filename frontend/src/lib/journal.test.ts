import { describe, expect, it } from "vitest";

import type { ResearchNoteItem } from "./journal";
import {
  beijingDayEndExclusiveIso,
  beijingDayStartIso,
  countResearchNotesByType,
  joinResearchNoteTags,
  parseResearchNoteTags,
  researchNoteQuery,
  researchNoteType,
  researchNoteTypeLabel,
} from "./journal";

function note(id: string, type: ResearchNoteItem["type"]): ResearchNoteItem {
  return {
    id,
    type,
    title: id,
    content: id,
    tags: [],
    created_at: "2026-11-10T23:00:00Z",
    updated_at: "2026-11-10T23:00:00Z",
  };
}

describe("研究记录类型标签", () => {
  it("四种类型映射成中文，未知取值原样返回", () => {
    expect(researchNoteTypeLabel("hypothesis")).toBe("假设");
    expect(researchNoteTypeLabel("backtest_conclusion")).toBe("回测结论");
    expect(researchNoteTypeLabel("decision")).toBe("决策");
    expect(researchNoteTypeLabel("review")).toBe("复盘");
    expect(researchNoteTypeLabel("custom")).toBe("custom");
  });

  it("只接受接口定义的四种类型", () => {
    expect(researchNoteType("decision")).toBe("decision");
    expect(researchNoteType("custom")).toBeNull();
    expect(researchNoteType(null)).toBeNull();
  });
});

describe("研究记录数量统计", () => {
  it("按接口返回的记录逐条计数", () => {
    const counts = countResearchNotesByType([
      note("rn_1", "hypothesis"),
      note("rn_2", "hypothesis"),
      note("rn_3", "review"),
      note("rn_4", "decision"),
    ]);

    expect(counts).toEqual({
      hypothesis: 2,
      backtest_conclusion: 0,
      decision: 1,
      review: 1,
    });
  });
});

describe("研究记录筛选查询串", () => {
  it("只写入实际设置的筛选条件", () => {
    const query = researchNoteQuery({ type: "review", sort: "created_at_asc" });

    expect(query.get("type")).toBe("review");
    expect(query.get("sort")).toBe("created_at_asc");
    expect(query.get("related_instrument_id")).toBeNull();
    expect(query.get("from")).toBeNull();
  });

  it("关联对象按接口字段名写入", () => {
    const query = researchNoteQuery({
      instrumentId: "AAPL-USDT-SWAP",
      strategyId: "st_0001",
      backtestId: "bt_0001",
    });

    expect(query.get("related_instrument_id")).toBe("AAPL-USDT-SWAP");
    expect(query.get("related_strategy_id")).toBe("st_0001");
    expect(query.get("related_backtest_id")).toBe("bt_0001");
  });

  it("北京时间日期按当天起止转换，截止日期包含当天", () => {
    expect(beijingDayStartIso("2026-11-10")).toBe("2026-11-09T16:00:00.000Z");
    expect(beijingDayEndExclusiveIso("2026-11-10")).toBe("2026-11-10T16:00:00.000Z");

    const query = researchNoteQuery({ from: "2026-11-10", to: "2026-11-10" });
    expect(query.get("from")).toBe("2026-11-09T16:00:00.000Z");
    expect(query.get("to")).toBe("2026-11-10T16:00:00.000Z");
  });

  it("无效日期不写入查询串", () => {
    expect(beijingDayStartIso("2026-02-30")).toBeNull();
    expect(beijingDayEndExclusiveIso("not-a-date")).toBeNull();
    const query = researchNoteQuery({ from: "2026-02-30", to: "not-a-date" });
    expect(query.get("from")).toBeNull();
    expect(query.get("to")).toBeNull();
  });
});

describe("研究记录标签输入", () => {
  it("按逗号或换行拆分、去空、去重并保持顺序", () => {
    expect(parseResearchNoteTags("趋势, 验证中\n趋势， 回测")).toEqual([
      "趋势",
      "验证中",
      "回测",
    ]);
  });

  it("空输入得到空数组，展示时用逗号连接", () => {
    expect(parseResearchNoteTags("  ")).toEqual([]);
    expect(joinResearchNoteTags(["趋势", "验证中"])).toBe("趋势, 验证中");
  });
});
