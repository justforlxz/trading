import { describe, expect, it } from "vitest";

import {
  changedRules,
  draftFromConfig,
  NOTIFY_CHANNELS,
  ruleCopy,
  toggleChannel,
  type RiskNotifyRule,
} from "./risk-notify";

const RULES: RiskNotifyRule[] = [
  {
    rule_id: "stop_missing",
    enabled: true,
    channels: ["browser"],
    threshold: null,
  },
  {
    rule_id: "high_leverage",
    enabled: true,
    channels: ["browser", "telegram"],
    threshold: "3",
  },
  {
    rule_id: "margin_usage",
    enabled: false,
    channels: ["browser"],
    threshold: "70",
  },
];

describe("通知规则文案", () => {
  it("五条规则都有中文标题与说明", () => {
    const ids = [
      "stop_missing",
      "stop_distance",
      "high_leverage",
      "single_instrument_weight",
      "margin_usage",
    ];
    for (const id of ids) {
      const copy = ruleCopy(id);
      expect(copy.title).not.toBe(id);
      expect(copy.description.length).toBeGreaterThan(0);
    }
  });

  it("未知规则原样显示 id，不显示空标题", () => {
    expect(ruleCopy("some_new_rule").title).toBe("some_new_rule");
  });

  it("未挂止损没有可调阈值", () => {
    expect(ruleCopy("stop_missing").unit).toBeNull();
    expect(ruleCopy("stop_distance").unit).toBe("倍 ATR");
  });

  it("渠道固定三种", () => {
    expect(NOTIFY_CHANNELS.map((item) => item.key)).toEqual([
      "browser",
      "telegram",
      "webhook",
    ]);
  });
});

describe("草稿与提交内容", () => {
  it("草稿来自当前配置", () => {
    const draft = draftFromConfig(RULES);

    expect(draft.stop_missing.enabled).toBe(true);
    expect(draft.high_leverage.channels).toEqual(["browser", "telegram"]);
    expect(draft.margin_usage.enabled).toBe(false);
    expect(draft.high_leverage.threshold).toBe("3");
  });

  it("没有改动就不提交任何规则", () => {
    expect(changedRules(RULES, draftFromConfig(RULES))).toEqual([]);
  });

  it("只提交改动过的规则", () => {
    const draft = draftFromConfig(RULES);
    draft.stop_missing.enabled = false;

    const updates = changedRules(RULES, draft);

    expect(updates).toHaveLength(1);
    expect(updates[0]).toEqual({ rule_id: "stop_missing", enabled: false });
  });

  it("阈值清空表示不修改，不会把空字符串写进配置", () => {
    const draft = draftFromConfig(RULES);
    draft.high_leverage.threshold = "   ";

    expect(changedRules(RULES, draft)).toEqual([]);
  });

  it("阈值改动会被正常提交", () => {
    const draft = draftFromConfig(RULES);
    draft.high_leverage.threshold = "5";

    expect(changedRules(RULES, draft)).toEqual([
      { rule_id: "high_leverage", threshold: "5" },
    ]);
  });

  it("渠道改动会被提交，顺序归一", () => {
    const draft = draftFromConfig(RULES);
    draft.high_leverage.channels = toggleChannel(draft.high_leverage.channels, "webhook");

    expect(changedRules(RULES, draft)).toEqual([
      { rule_id: "high_leverage", channels: ["browser", "telegram", "webhook"] },
    ]);
  });
});

describe("渠道开关", () => {
  it("打开一个渠道时按固定顺序排列", () => {
    expect(toggleChannel(["telegram"], "webhook")).toEqual(["telegram", "webhook"]);
    expect(toggleChannel(["webhook"], "browser")).toEqual(["browser", "webhook"]);
  });

  it("再次点击就取消", () => {
    expect(toggleChannel(["browser", "telegram"], "browser")).toEqual(["telegram"]);
  });
});
