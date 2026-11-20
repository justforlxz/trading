/**
 * 设置页的输入文本与接口字段之间的转换。
 *
 * “订阅标的”在界面上是逗号分隔的一行文本，接口里是字符串数组。输入过程必须保留
 * 用户原始文本（包括刚键入、尚未写完的逗号），否则逐项键入时逗号会被立刻过滤掉。
 * 因此解析只在保存时发生，页面拿到的是纯函数结果。
 */

import type {
  DisplaySettings,
  ExecutionSettings,
  NotificationSettings,
  RiskDefaults,
  SettingsResponse,
} from "./api";

/** 设置页的草稿：只放可编辑字段，订阅标的原文由页面单独持有。 */
export type SettingsDraft = {
  display: DisplaySettings;
  risk_defaults: RiskDefaults;
  execution: ExecutionSettings;
  notifications: NotificationSettings;
};

export function toSettingsDraft(settings: SettingsResponse): SettingsDraft {
  return {
    display: settings.display,
    risk_defaults: settings.risk_defaults,
    execution: settings.execution,
    notifications: settings.notifications,
  };
}

/** 接口返回的标的数组 → 输入框文本。 */
export function instrumentsToText(instruments: readonly string[]): string {
  return instruments.join(", ");
}

/** 输入框文本 → 标的数组；只去掉空白项，不改变用户键入的其它内容。 */
export function parseInstruments(text: string): string[] {
  return text
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item !== "");
}
