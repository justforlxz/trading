/**
 * 风控通知设置的只读客户端与展示文案。
 *
 * 五条规则与它们的阈值都由后端给出，这里只负责把规则的英文 id 映射成中文标题与
 * 说明文字，并把提交内容整理成契约需要的形状。页面不判断阈值、不算命中数。
 */

import type { components } from "../api/types";
import { request } from "./api";

export type RiskNotifyConfig = components["schemas"]["RiskNotifyConfigResponse"];
export type RiskNotifyRule = RiskNotifyConfig["rules"][number];
export type RiskNotifyUpdate = components["schemas"]["RiskNotifyConfigUpdateRequest"];
export type NotifyChannel = RiskNotifyRule["channels"][number];

export const NOTIFY_CHANNELS: readonly { key: NotifyChannel; label: string }[] = [
  { key: "browser", label: "浏览器" },
  { key: "telegram", label: "Telegram" },
  { key: "webhook", label: "Webhook" },
];

export type RuleCopy = {
  title: string;
  description: string;
  /** 阈值单位；`null` 表示这条规则没有可调阈值。 */
  unit: string | null;
  /** 阈值输入框前的说明，如「超过」「小于」。 */
  comparator: string | null;
};

const RULE_COPY: Record<string, RuleCopy> = {
  stop_missing: {
    title: "未挂止损",
    description: "持仓没有止盈止损挂单时提醒（数据来自 OKX 策略委托）",
    unit: null,
    comparator: null,
  },
  stop_distance: {
    title: "止损距离过近",
    description: "标记价到止损的距离小于设定倍数时提醒",
    unit: "倍 ATR",
    comparator: "小于",
  },
  high_leverage: {
    title: "杠杆过高",
    description: "单个持仓的杠杆超过阈值时提醒",
    unit: "倍",
    comparator: "超过",
  },
  single_instrument_weight: {
    title: "单标的占比过大",
    description: "单个标的占组合名义敞口的比例超过阈值时提醒",
    unit: "%",
    comparator: "超过",
  },
  margin_usage: {
    title: "保证金占用过高",
    description: "整个账户的保证金使用率超过阈值时提醒",
    unit: "%",
    comparator: "超过",
  },
};

/** 未知规则原样显示 id：后端新增规则时不该让界面崩掉或显示空标题。 */
export function ruleCopy(ruleId: string): RuleCopy {
  return (
    RULE_COPY[ruleId] ?? {
      title: ruleId,
      description: "",
      unit: null,
      comparator: null,
    }
  );
}

export function fetchRiskNotifyConfig(): Promise<RiskNotifyConfig> {
  return request<RiskNotifyConfig>("/risk/notify-config");
}

export function saveRiskNotifyConfig(rules: RiskNotifyUpdate["rules"]): Promise<RiskNotifyConfig> {
  return request<RiskNotifyConfig>("/risk/notify-config", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ rules }),
  });
}

export type NotifyDraft = {
  enabled: boolean;
  channels: NotifyChannel[];
  /** 输入框里的原文；空字符串表示不改阈值。 */
  threshold: string;
};

export function draftFromConfig(rules: readonly RiskNotifyRule[]): Record<string, NotifyDraft> {
  const draft: Record<string, NotifyDraft> = {};
  for (const rule of rules) {
    draft[rule.rule_id] = {
      enabled: rule.enabled,
      channels: [...rule.channels],
      threshold: rule.threshold ?? "",
    };
  }
  return draft;
}

/**
 * 只提交真正改过的规则。
 *
 * 全部规则一起回写也能用，但那样每次保存都会改写五条规则的 `updated_at`，事后无法
 * 分辨哪条是用户真正动过的。
 */
export function changedRules(
  original: readonly RiskNotifyRule[],
  draft: Record<string, NotifyDraft>,
): RiskNotifyUpdate["rules"] {
  const updates: RiskNotifyUpdate["rules"] = [];
  for (const rule of original) {
    const current = draft[rule.rule_id];
    if (current === undefined) continue;
    const patch: RiskNotifyUpdate["rules"][number] = { rule_id: rule.rule_id };
    let changed = false;
    if (current.enabled !== rule.enabled) {
      patch.enabled = current.enabled;
      changed = true;
    }
    if (!sameChannels(current.channels, rule.channels)) {
      patch.channels = current.channels;
      changed = true;
    }
    const originalThreshold = rule.threshold ?? "";
    if (current.threshold !== originalThreshold && current.threshold.trim() !== "") {
      patch.threshold = current.threshold.trim();
      changed = true;
    }
    if (changed) updates.push(patch);
  }
  return updates;
}

function sameChannels(left: readonly NotifyChannel[], right: readonly NotifyChannel[]): boolean {
  return left.length === right.length && left.every((name) => right.includes(name));
}

/** 打开某条规则的开关时至少留一个渠道，否则后端会拒绝保存。 */
export function toggleChannel(
  channels: readonly NotifyChannel[],
  channel: NotifyChannel,
): NotifyChannel[] {
  const wanted = channels.includes(channel)
    ? channels.filter((name) => name !== channel)
    : [...channels, channel];
  // 按固定顺序归一：同一份选择不该因为勾选顺序不同而写成两种数组。
  return NOTIFY_CHANNELS.filter((item) => wanted.includes(item.key)).map((item) => item.key);
}
