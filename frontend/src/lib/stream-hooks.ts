/** React 绑定：把共享推送连接的状态与事件映射成页面可用的状态。 */

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useNavigate } from "react-router-dom";

import {
  NotifiedAlerts,
  alertNavigationPath,
  currentPermissionState,
  notifyAlert,
  type NotificationDeps,
} from "./notifications";
import {
  acceptsUpdate,
  streamClient,
  streamLiveness,
  type AccountUpdate,
  type PositionUpdate,
  type QuoteUpdate,
  type StreamEvent,
  type StreamLiveness,
  type StreamState,
} from "./stream";

export function useStreamState(): StreamState {
  return useSyncExternalStore(streamClient.subscribeState, streamClient.getState);
}

/** 只订阅数据源连接状态；不在本页请求行情，也不启动上游行情连接。 */
export function useDataSourceStatus(): StreamState {
  const state = useStreamState();
  const owner = useOwner();
  useEffect(() => {
    streamClient.setSubscription(owner, { status: true });
    return () => streamClient.clearSubscription(owner);
  }, [owner]);
  return state;
}

function useStreamEvents(handler: (event: StreamEvent) => void): void {
  const latest = useRef(handler);
  latest.current = handler;
  useEffect(() => {
    return streamClient.subscribeEvents((event) => latest.current(event));
  }, []);
}

function useOwner(): symbol {
  const owner = useRef<symbol>();
  if (owner.current === undefined) owner.current = Symbol("stream-subscription");
  return owner.current;
}

/** 订阅当前可见标的的行情；集合变化时按后端能力追加订阅或重建连接。 */
export function useQuoteStream(instIds: readonly string[]): {
  quotes: Record<string, QuoteUpdate>;
  liveness: StreamLiveness;
} {
  const state = useStreamState();
  const owner = useOwner();
  const [quotes, setQuotes] = useState<Record<string, QuoteUpdate>>({});
  const key = [...new Set(instIds)].sort().join("\n");

  useStreamEvents((event) => {
    if (event.type !== "market.quote.updated") return;
    const next = {
      ...event.data,
      as_of: event.asOf,
      received_at: event.receivedAt,
    };
    setQuotes((previous) =>
      acceptsUpdate(next, previous[next.inst_id])
        ? { ...previous, [next.inst_id]: next }
        : previous,
    );
  });

  useEffect(() => {
    streamClient.setSubscription(owner, {
      quotes: key === "" ? [] : key.split("\n"),
    });
    return () => streamClient.clearSubscription(owner);
  }, [key, owner]);

  return { quotes, liveness: streamLiveness(state, "public_ws") };
}

/** 持仓页订阅账户与持仓；推送只覆盖价格、盈亏与账户快照字段。 */
export function usePositionStream(): {
  positions: Record<string, PositionUpdate>;
  account: AccountUpdate | null;
  liveness: StreamLiveness;
} {
  const state = useStreamState();
  const owner = useOwner();
  const [positions, setPositions] = useState<Record<string, PositionUpdate>>({});
  const [account, setAccount] = useState<AccountUpdate | null>(null);

  useStreamEvents((event) => {
    if (event.type === "position.updated") {
      const next = {
        ...event.data,
        as_of: event.asOf,
        received_at: event.receivedAt,
      };
      setPositions((previous) =>
        acceptsUpdate(next, previous[next.pos_id])
          ? { ...previous, [next.pos_id]: next }
          : previous,
      );
    } else if (event.type === "account.snapshot.updated") {
      const next = { ...event.data, as_of: event.asOf, received_at: event.receivedAt };
      setAccount((previous) => (acceptsUpdate(next, previous ?? undefined) ? next : previous));
    }
  });

  useEffect(() => {
    streamClient.setSubscription(owner, { account: true, positions: true });
    return () => streamClient.clearSubscription(owner);
  }, [owner]);

  return { positions, account, liveness: streamLiveness(state, "private_ws") };
}

/**
 * 浏览器通知：订阅 `alerts` 通道，把新告警弹成系统通知。
 *
 * 有没有告警推下来由服务端的通道开关决定（`settings.notifications.channels`）；这里
 * 只负责订阅与展示。通知失败（未授权、浏览器不支持、重复告警）都在
 * `notifications.ts` 里被吞掉，页面不会因此出错。
 */
export function useAlertNotifications(): void {
  const owner = useOwner();
  const navigate = useNavigate();
  const seen = useRef<NotifiedAlerts>();

  if (seen.current === undefined) seen.current = new NotifiedAlerts();

  useStreamEvents((event) => {
    if (event.type !== "alert.created") return;
    notifyAlert(event.data, {
      notification: browserNotification(),
      permission: currentPermissionState(),
      seen: seen.current as NotifiedAlerts,
      onActivate: (alert) => {
        const path = alertNavigationPath(alert);
        if (path !== null) navigate(path);
      },
    });
  });

  useEffect(() => {
    streamClient.setSubscription(owner, { alerts: true });
    return () => streamClient.clearSubscription(owner);
  }, [owner]);
}

function browserNotification(): NotificationDeps["notification"] {
  if (typeof window === "undefined" || !("Notification" in window)) return null;
  return window.Notification;
}
