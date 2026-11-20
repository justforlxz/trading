/**
 * 浏览器通知：权限状态、弹出通知、点击跳转与去重。
 *
 * 边界（页面上也这样写，不假装支持做不到的事）：
 * - Notification API 只能由页面调用，权限必须在用户手势里申请，服务端无法替用户授权；
 * - 通知只在页面存在时有效，包括后台标签页；页面关闭后服务端仍会推送，但没有人弹窗；
 * - 权限被拒绝或用户没授权时不弹窗、不报错，只在设置页显示当前状态。
 *
 * 去重按 `alert_id` 记在内存与 `sessionStorage`：断线重连会重新收到同一批快照式的
 * 告警，用户不应该被同一个告警弹第二次。
 */

import type { AlertCreatedData } from "./stream";

export type NotificationPermissionState = "granted" | "denied" | "default" | "unsupported";

export const NOTIFIED_ALERTS_KEY = "trading.notified-alerts";
const NOTIFIED_LIMIT = 200;

/** 浏览器不支持 Notification 时返回 `unsupported`，不把它当成「未授权」。 */
export function permissionState(value: string | null | undefined): NotificationPermissionState {
  if (value === "granted" || value === "denied" || value === "default") return value;
  return "unsupported";
}

export function notificationPermissionLabel(state: NotificationPermissionState): string {
  switch (state) {
    case "granted":
      return "已允许，新提醒会弹出系统通知";
    case "denied":
      return "已被浏览器拒绝，需要在浏览器站点设置里手动改回允许";
    case "default":
      return "尚未授权，点击「开启浏览器通知」后由浏览器询问";
    default:
      return "当前浏览器不支持系统通知";
  }
}

/** 点击通知跳转到该标的详情页；没有标的的提醒只聚焦窗口，不跳转。 */
export function alertNavigationPath(alert: { instrument_id: string | null }): string | null {
  const instId = alert.instrument_id;
  if (instId === null || instId.trim() === "") return null;
  return `/watchlist/${encodeURIComponent(instId.trim())}`;
}

export function alertNotificationTitle(alert: AlertCreatedData): string {
  return alert.title.trim() === "" ? "新提醒" : alert.title;
}

export function alertNotificationBody(alert: AlertCreatedData): string {
  return alert.detail;
}

type StorageLike = Pick<Storage, "getItem" | "setItem">;

/** 已弹过的告警标识：内存 + `sessionStorage`，刷新后仍不重复弹。 */
export class NotifiedAlerts {
  private readonly ids: Set<string>;
  private readonly storage: StorageLike | null;
  private readonly limit: number;

  constructor(storage: StorageLike | null = safeSessionStorage(), limit = NOTIFIED_LIMIT) {
    this.storage = storage;
    this.limit = limit;
    this.ids = this.load();
  }

  has(id: string): boolean {
    return this.ids.has(id);
  }

  add(id: string): void {
    this.ids.add(id);
    this.persist();
  }

  private load(): Set<string> {
    const raw = this.storage?.getItem(NOTIFIED_ALERTS_KEY);
    if (raw === null || raw === undefined || raw === "") return new Set();
    try {
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return new Set();
      return new Set(parsed.filter((item): item is string => typeof item === "string"));
    } catch {
      // 存的内容坏了就当作空集合，不影响本次通知。
      return new Set();
    }
  }

  private persist(): void {
    if (this.storage === null) return;
    const values = [...this.ids].slice(-this.limit);
    try {
      this.storage.setItem(NOTIFIED_ALERTS_KEY, JSON.stringify(values));
    } catch {
      // sessionStorage 写满或被禁用时只影响下次去重，不影响本次弹窗。
    }
  }
}

function safeSessionStorage(): StorageLike | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

type NotificationLike = {
  onclick: ((this: Notification, ev: Event) => unknown) | null;
  close: () => void;
};

export type NotificationDeps = {
  /** 构造函数形态；缺省读 `window.Notification`，测试可注入假实现。 */
  notification: (new (title: string, options?: NotificationOptions) => NotificationLike) | null;
  permission: NotificationPermissionState;
  seen: NotifiedAlerts;
  onActivate: (alert: AlertCreatedData) => void;
};

/**
 * 弹一条系统通知。返回是否真的弹出来了：权限不足与重复告警都返回 `false`，
 * 并且不抛错——后台通知失败不应该影响页面。
 */
export function notifyAlert(alert: AlertCreatedData, deps: NotificationDeps): boolean {
  if (deps.permission !== "granted" || deps.notification === null) return false;
  if (deps.seen.has(alert.id)) return false;
  let notification: NotificationLike;
  try {
    notification = new deps.notification(alertNotificationTitle(alert), {
      body: alertNotificationBody(alert),
      tag: alert.id,
    });
  } catch {
    return false;
  }
  notification.onclick = () => {
    deps.onActivate(alert);
    try {
      window.focus();
    } catch {
      // 有些浏览器在后台标签页里禁止聚焦，忽略即可。
    }
    notification.close();
  };
  deps.seen.add(alert.id);
  return true;
}

/** 当前权限；浏览器没有 Notification 时返回 `unsupported`。 */
export function currentPermissionState(): NotificationPermissionState {
  if (typeof window === "undefined" || !("Notification" in window)) return "unsupported";
  return permissionState(window.Notification.permission);
}
