import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import { ActivityTimeline } from "./activity-timeline";

describe("活动时间线", () => {
  it("摘要与事件类型来自接口数据", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityTimeline, {
        items: [
          {
            id: "ac_1",
            event_type: "alert.acknowledged",
            summary: "提醒「持仓缺少止损」已确认",
            created_at: "2026-11-10T09:00:00Z",
          },
        ],
      }),
    );
    expect(html).toContain("提醒「持仓缺少止损」已确认");
    expect(html).toContain("提醒已确认");
    expect(html).toContain("2026-11-10 17:00");
  });

  it("空列表使用调用方给的文案", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityTimeline, { items: [], emptyText: "当前筛选没有活动流水。" }),
    );
    expect(html).toContain("当前筛选没有活动流水。");
  });
});
