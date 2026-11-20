import { describe, expect, it } from "vitest";

import {
  NOTIFIED_ALERTS_KEY,
  NotifiedAlerts,
  alertNavigationPath,
  notificationPermissionLabel,
  notifyAlert,
  permissionState,
  type NotificationDeps,
} from "./notifications";
import type { AlertCreatedData } from "./stream";

const ALERT: AlertCreatedData = {
  id: "al_1",
  type: "price",
  severity: "warning",
  instrument_id: "XAAPL-USDT",
  title: "价格偏离参考价",
  detail: "XAAPL-USDT 最新成交价 110 高于 指数价 100，偏离 10%",
  triggered_at: "2026-11-20T12:00:00Z",
};

class MemoryStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

class FakeNotification {
  static created: FakeNotification[] = [];
  static failNext = false;

  onclick: ((this: Notification, ev: Event) => unknown) | null = null;
  closed = false;

  constructor(
    readonly title: string,
    readonly options?: NotificationOptions,
  ) {
    if (FakeNotification.failNext) {
      FakeNotification.failNext = false;
      throw new Error("浏览器拒绝创建通知");
    }
    FakeNotification.created.push(this);
  }

  close(): void {
    this.closed = true;
  }

  click(): void {
    this.onclick?.call(this as unknown as Notification, {} as Event);
  }
}

function deps(overrides: Partial<NotificationDeps> = {}): NotificationDeps {
  return {
    notification: FakeNotification as unknown as NotificationDeps["notification"],
    permission: "granted",
    seen: new NotifiedAlerts(new MemoryStorage()),
    onActivate: () => undefined,
    ...overrides,
  };
}

describe("权限状态", () => {
  it("浏览器权限映射成四种状态，未知值当作不支持", () => {
    expect(permissionState("granted")).toBe("granted");
    expect(permissionState("denied")).toBe("denied");
    expect(permissionState("default")).toBe("default");
    expect(permissionState(undefined)).toBe("unsupported");
  });

  it("每种状态都有人能看懂的中文说明", () => {
    expect(notificationPermissionLabel("granted")).toContain("已允许");
    expect(notificationPermissionLabel("denied")).toContain("浏览器");
    expect(notificationPermissionLabel("default")).toContain("尚未授权");
    expect(notificationPermissionLabel("unsupported")).toContain("不支持");
  });
});

describe("单击通知跳转", () => {
  it("有标的时跳到该标的详情页", () => {
    expect(alertNavigationPath(ALERT)).toBe("/watchlist/XAAPL-USDT");
  });

  it("没有标的时不跳转，只聚焦窗口", () => {
    expect(alertNavigationPath({ instrument_id: null })).toBeNull();
    expect(alertNavigationPath({ instrument_id: "   " })).toBeNull();
  });
});

describe("弹出通知", () => {
  it("已授权时弹一条通知并使用告警内容", () => {
    FakeNotification.created = [];

    const shown = notifyAlert(ALERT, deps());

    expect(shown).toBe(true);
    expect(FakeNotification.created).toHaveLength(1);
    expect(FakeNotification.created[0].title).toBe("价格偏离参考价");
    expect(FakeNotification.created[0].options?.body).toBe(ALERT.detail);
    expect(FakeNotification.created[0].options?.tag).toBe("al_1");
  });

  it("点击通知后触发跳转并关闭通知", () => {
    FakeNotification.created = [];
    const activated: AlertCreatedData[] = [];

    notifyAlert(ALERT, deps({ onActivate: (alert) => activated.push(alert) }));
    FakeNotification.created[0].click();

    expect(activated).toEqual([ALERT]);
    expect(FakeNotification.created[0].closed).toBe(true);
  });

  it("未授权或被拒绝时不弹窗，也不抛错", () => {
    FakeNotification.created = [];

    expect(notifyAlert(ALERT, deps({ permission: "default" }))).toBe(false);
    expect(notifyAlert(ALERT, deps({ permission: "denied" }))).toBe(false);
    expect(notifyAlert(ALERT, deps({ permission: "unsupported" }))).toBe(false);
    expect(FakeNotification.created).toHaveLength(0);
  });

  it("浏览器没有 Notification 时不弹窗", () => {
    expect(notifyAlert(ALERT, deps({ notification: null }))).toBe(false);
  });

  it("浏览器拒绝创建通知时返回 false", () => {
    FakeNotification.created = [];
    FakeNotification.failNext = true;

    expect(notifyAlert(ALERT, deps())).toBe(false);
  });
});

describe("去重", () => {
  it("同一个 alert_id 只弹一次", () => {
    FakeNotification.created = [];
    const shared = deps();

    expect(notifyAlert(ALERT, shared)).toBe(true);
    expect(notifyAlert(ALERT, shared)).toBe(false);
    expect(FakeNotification.created).toHaveLength(1);
  });

  it("已弹过的标识写进 sessionStorage，刷新后不再弹", () => {
    FakeNotification.created = [];
    const storage = new MemoryStorage();
    notifyAlert(ALERT, deps({ seen: new NotifiedAlerts(storage) }));

    expect(JSON.parse(storage.getItem(NOTIFIED_ALERTS_KEY) ?? "[]")).toEqual(["al_1"]);
    expect(notifyAlert(ALERT, deps({ seen: new NotifiedAlerts(storage) }))).toBe(false);
  });

  it("存的内容损坏时当作空集合，不影响本次弹窗", () => {
    const storage = new MemoryStorage();
    storage.setItem(NOTIFIED_ALERTS_KEY, "not json");

    const seen = new NotifiedAlerts(storage);

    expect(seen.has("al_1")).toBe(false);
  });

  it("没有 storage 时只在内存里去重", () => {
    const seen = new NotifiedAlerts(null);
    seen.add("al_1");

    expect(seen.has("al_1")).toBe(true);
  });
});
