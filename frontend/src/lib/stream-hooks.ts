/** React 绑定：把共享推送连接的状态与事件映射成页面可用的状态。 */

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

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
