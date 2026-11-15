import { describe, expect, it } from "vitest";

import { ACTIVITY_EVENT_OPTIONS, activityEventLabel, activityQuery } from "./activity";

describe("活动流水筛选", () => {
  it("已知事件类型显示中文名，未知类型原样返回", () => {
    expect(activityEventLabel("alert.acknowledged")).toBe("提醒已确认");
    expect(activityEventLabel("custom.event")).toBe("custom.event");
    expect(ACTIVITY_EVENT_OPTIONS.some((option) => option.value === "alert.ignored")).toBe(true);
  });

  it("日期按北京时间当天换算成 UTC ISO，截止日期含当天", () => {
    const query = activityQuery({
      eventType: "alert.acknowledged",
      from: "2026-11-10",
      to: "2026-11-11",
    });
    expect(query.get("event_type")).toBe("alert.acknowledged");
    expect(query.get("from")).toBe("2026-11-09T16:00:00.000Z");
    expect(query.get("to")).toBe("2026-11-11T16:00:00.000Z");
  });

  it("没有设置条件时不写查询参数", () => {
    expect(activityQuery({}).toString()).toBe("");
  });
});
