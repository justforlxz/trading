/**
 * 设置页的输入文本与接口字段之间的转换。
 *
 * “订阅标的”在界面上是逗号分隔的一行文本，接口里是字符串数组。输入过程必须保留
 * 用户原始文本（包括刚键入、尚未写完的逗号），否则逐项键入时逗号会被立刻过滤掉。
 * 因此解析只在保存时发生，页面拿到的是纯函数结果。
 *
 * 通知分组在接口里是嵌套的（`channels` / `telegram.chat_id` / `webhook.url`），
 * 界面上是三条独立输入。草稿因此拍平成三个字段，保存时再由 `notificationsPatch`
 * 组装回接口形状：这样切换某个通道开关不会顺手覆盖另一个通道的接收方。
 */

import type {
  DisplaySettings,
  ExecutionSettings,
  NotificationSettings,
  NotificationSettingsUpdate,
  RiskDefaults,
  SettingsResponse,
} from "./api";

/** 通知分组在草稿里的扁平形状：接收方各自一条，与界面输入一一对应。 */
export type NotificationDraft = {
  channels: string[];
  telegramChatId: string;
  webhookUrl: string;
};

/** 设置页的草稿：只放可编辑字段，订阅标的原文由页面单独持有。 */
export type SettingsDraft = {
  display: DisplaySettings;
  risk_defaults: RiskDefaults;
  execution: ExecutionSettings;
  notifications: NotificationDraft;
};

/** 三个通道的固定顺序：界面按这个顺序排列开关。 */
export const NOTIFICATION_CHANNELS: readonly string[] = ["browser", "telegram", "webhook"];

export function toSettingsDraft(settings: SettingsResponse): SettingsDraft {
  return {
    display: settings.display,
    risk_defaults: settings.risk_defaults,
    execution: settings.execution,
    notifications: toNotificationDraft(settings.notifications),
  };
}

/** 接口的通知分组 → 扁平草稿；缺项按「未配置」处理。 */
export function toNotificationDraft(notifications: NotificationSettings): NotificationDraft {
  return {
    channels: [...(notifications.channels ?? [])],
    telegramChatId: notifications.telegram?.chat_id ?? "",
    webhookUrl: notifications.webhook?.url ?? "",
  };
}

/**
 * 切换一个通道开关，保留其它通道的原有开关状态。
 *
 * 只按名字增删，不重排已有项：后端按提交顺序落库，顺序变了只是噪音。
 */
export function withChannel(
  channels: readonly string[],
  channel: string,
  enabled: boolean,
): string[] {
  const rest = channels.filter((item) => item !== channel);
  return enabled ? [...rest, channel] : rest;
}

/** 草稿 → 通知分组的 PATCH 载荷：三个子项一次给全，接收方为空表示清空。 */
export function notificationsPatch(draft: NotificationDraft): NotificationSettingsUpdate {
  return {
    channels: [...draft.channels],
    telegram: { chat_id: draft.telegramChatId.trim() },
    webhook: { url: draft.webhookUrl.trim() },
  };
}

/** 通道名的中文标签；未登记的通道名原样显示，不伪造解释。 */
export function channelLabel(channel: string): string {
  if (channel === "browser") return "浏览器";
  if (channel === "telegram") return "Telegram";
  if (channel === "webhook") return "Webhook";
  return channel;
}

/** 凭据状态：接口只给布尔，页面只能显示这两种说法。 */
export function credentialText(configured: boolean): string {
  return configured ? "已配置" : "未配置";
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
