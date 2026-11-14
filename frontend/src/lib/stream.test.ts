import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  StreamClient,
  acceptsUpdate,
  streamLiveness,
  streamStatusLabel,
  updateTime,
  type SocketLike,
  type StreamEvent,
  type StreamState,
} from "./stream";

const OPEN = 1;

class FakeSocket implements SocketLike {
  static instances: FakeSocket[] = [];

  readyState = 0;
  sent: string[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = 3;
  }

  open(): void {
    this.readyState = OPEN;
    this.onopen?.({} as Event);
  }

  message(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }

  drop(): void {
    this.readyState = 3;
    this.onclose?.({} as CloseEvent);
  }
}

function createClient(): StreamClient {
  return new StreamClient({
    url: () => "ws://test/api/stream",
    socketFactory: (url) => new FakeSocket(url),
  });
}

function topicsOf(socket: FakeSocket, index = 0): unknown {
  return JSON.parse(socket.sent[index]).topics;
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("StreamClient 连接与订阅", () => {
  it("连接成功后发送后端要求的订阅消息", () => {
    const client = createClient();
    const owner = Symbol("page");

    client.start();
    expect(client.getState().status).toBe("connecting");

    const socket = FakeSocket.instances[0];
    socket.open();
    expect(client.getState().status).toBe("connected");

    client.setSubscription(owner, { quotes: ["ETH-USDT", "BTC-USDT"] });
    expect(topicsOf(socket)).toEqual([
      { type: "quote", inst_ids: ["BTC-USDT", "ETH-USDT"] },
    ]);
  });

  it("订阅集合缩小时重建连接，因为后端没有退订消息", () => {
    const client = createClient();
    const owner = Symbol("page");
    client.start();
    FakeSocket.instances[0].open();

    client.setSubscription(owner, { quotes: ["BTC-USDT", "ETH-USDT"] });
    client.setSubscription(owner, { quotes: ["BTC-USDT"] });

    expect(FakeSocket.instances).toHaveLength(2);
    const next = FakeSocket.instances[1];
    next.open();
    expect(topicsOf(next)).toEqual([{ type: "quote", inst_ids: ["BTC-USDT"] }]);
  });

  it("订阅集合扩大时沿用同一条连接，只追加订阅", () => {
    const client = createClient();
    const owner = Symbol("page");
    client.start();
    const socket = FakeSocket.instances[0];
    socket.open();

    client.setSubscription(owner, { quotes: ["BTC-USDT"] });
    client.setSubscription(owner, { quotes: ["BTC-USDT", "ETH-USDT"] });

    expect(FakeSocket.instances).toHaveLength(1);
    expect(topicsOf(socket, 1)).toEqual([
      { type: "quote", inst_ids: ["BTC-USDT", "ETH-USDT"] },
    ]);
  });

  it("断线后按退避重连，恢复后重新订阅当前集合", async () => {
    const client = createClient();
    const owner = Symbol("page");
    client.start();
    const first = FakeSocket.instances[0];
    first.open();
    client.setSubscription(owner, { quotes: ["BTC-USDT"] });

    first.drop();
    expect(client.getState().status).toBe("reconnecting");

    await vi.advanceTimersByTimeAsync(999);
    expect(FakeSocket.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.instances).toHaveLength(2);

    const second = FakeSocket.instances[1];
    second.open();
    expect(client.getState().status).toBe("connected");
    expect(topicsOf(second)).toEqual([{ type: "quote", inst_ids: ["BTC-USDT"] }]);
  });

  it("连续失败时退避时间递增", async () => {
    const client = createClient();
    client.start();
    FakeSocket.instances[0].drop();

    await vi.advanceTimersByTimeAsync(1_000);
    expect(FakeSocket.instances).toHaveLength(2);
    FakeSocket.instances[1].drop();

    await vi.advanceTimersByTimeAsync(1_999);
    expect(FakeSocket.instances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.instances).toHaveLength(3);
  });

  it("stop 之后不再自动重连", async () => {
    const client = createClient();
    client.start();
    FakeSocket.instances[0].drop();
    client.stop();

    await vi.advanceTimersByTimeAsync(60_000);
    expect(client.getState().status).toBe("disconnected");
    expect(FakeSocket.instances).toHaveLength(1);
  });
});

describe("StreamClient 事件解析", () => {
  it("解析行情事件并保留信封时间", () => {
    const client = createClient();
    const events: StreamEvent[] = [];
    client.subscribeEvents((event) => events.push(event));
    client.start();
    const socket = FakeSocket.instances[0];
    socket.open();

    socket.message({
      type: "market.quote.updated",
      as_of: "2026-11-14T10:00:00Z",
      received_at: "2026-11-14T10:00:01Z",
      data: {
        inst_id: "BTC-USDT",
        last: "91234.5",
        mark: null,
        index: null,
        source: "okx_ws",
        stale: false,
        snapshot: false,
      },
    });

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      type: "market.quote.updated",
      asOf: "2026-11-14T10:00:00Z",
      data: { inst_id: "BTC-USDT", last: "91234.5", source: "okx_ws" },
    });
    expect(client.getState().lastEventAt).toBe("2026-11-14T10:00:01Z");
  });

  it("记录数据源连接状态，供页面判断是否陈旧", () => {
    const client = createClient();
    client.start();
    const socket = FakeSocket.instances[0];
    socket.open();

    socket.message({
      type: "data_source.status.updated",
      as_of: null,
      received_at: "2026-11-14T10:00:01Z",
      data: { dataset: "public_ws", connected: false },
    });

    expect(client.getState().datasets.public_ws).toBe(false);
    expect(streamLiveness(client.getState(), "public_ws")).toBe("stale");
  });

  it("忽略格式错误的消息", () => {
    const client = createClient();
    client.start();
    const socket = FakeSocket.instances[0];
    socket.open();

    expect(() => socket.message("not-json")).not.toThrow();
    expect(() => socket.message({ type: "market.quote.updated", data: {} })).not.toThrow();
    expect(client.getState().status).toBe("connected");
  });
});

describe("连接状态文案", () => {
  it("顶栏使用真实连接状态对应的文字", () => {
    expect(streamStatusLabel("connected")).toBe("已连接");
    expect(streamStatusLabel("reconnecting")).toBe("重连中");
    expect(streamStatusLabel("disconnected")).toBe("未连接");
    expect(streamStatusLabel("idle")).toBe("未连接");
  });

  it("数据源断开时判为陈旧，连接未建立时判为连接中", () => {
    const state = (patch: Partial<StreamState>): StreamState => ({
      status: "connected",
      datasets: {},
      lastEventAt: null,
      ...patch,
    });

    expect(streamLiveness(state({}), "public_ws")).toBe("live");
    expect(streamLiveness(state({ status: "idle" }), "public_ws")).toBe("connecting");
    expect(streamLiveness(state({ status: "connecting" }), "public_ws")).toBe("connecting");
    expect(streamLiveness(state({ datasets: { public_ws: false } }), "public_ws")).toBe("stale");
    expect(streamLiveness(state({ status: "reconnecting" }), "public_ws")).toBe("stale");
  });

  it("只接受不早于当前值的事件，避免乱序回退", () => {
    const older = { as_of: "2026-11-13T08:00:00Z", received_at: null };
    const newer = { as_of: "2026-11-13T09:00:00Z", received_at: null };
    const account = {
      as_of: null,
      received_at: null,
      captured_at: "2026-11-13T09:00:00Z",
    };

    expect(acceptsUpdate(older, newer)).toBe(false);
    expect(acceptsUpdate(newer, older)).toBe(true);
    expect(acceptsUpdate(older, undefined)).toBe(true);
    expect(updateTime(account)).toBe("2026-11-13T09:00:00Z");
  });
});
