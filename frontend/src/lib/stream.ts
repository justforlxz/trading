/**
 * 浏览器实时推送客户端：连接 `/api/stream`，按页面订阅行情、账户与持仓。
 *
 * 协议来源在后端 `backend/app/stream/hub.py`：
 * - 订阅消息 `{action: "subscribe", topics: [...]}`：`hub.py:282-332`
 * - 行情订阅 `{type: "quote", inst_ids: [...]}`：`hub.py:304-313`
 * - 事件信封 `{type, as_of, received_at, data}`：`hub.py:861-872`
 * - 行情数据 `{inst_id, last, mark, index, source, stale, snapshot}`：`hub.py:157-166`
 * - 账户数据：`hub.py:895-930`；持仓数据：`hub.py:932-955`
 * - 数据源状态 `{dataset, connected, ...}`：`hub.py:779-791`
 *
 * 后端没有退订消息，订阅集合只能通过关闭连接清除；集合缩小时本客户端重连一次。
 */

export type StreamStatus = "idle" | "connecting" | "connected" | "reconnecting" | "disconnected";

export type StreamDataset = "public_ws" | "private_ws";

export type QuoteData = {
  inst_id: string;
  last: string | null;
  mark: string | null;
  index: string | null;
  source: string;
  stale: boolean;
  snapshot: boolean;
};

export type PositionData = {
  pos_id: string;
  inst_id: string;
  display_symbol: string | null;
  name: string | null;
  asset_class: string | null;
  pos_side: string | null;
  size: string | null;
  avg_px: string | null;
  mark_px: string | null;
  upl: string | null;
  upl_ratio: string | null;
  lever: string | null;
  mgn_mode: string | null;
  liq_px: string | null;
  margin: string | null;
};

export type AccountData = {
  account_id: string;
  currency: string | null;
  equity: string | null;
  available_equity: string | null;
  cash_balance: string | null;
  unrealized_pnl: string | null;
  used_margin: string | null;
  available_margin: string | null;
  margin_usage_pct: string | null;
  captured_at: string | null;
  source: string | null;
};

type Envelope = { asOf: string | null; receivedAt: string | null };

/** 页面拿到的事件数据连同信封里的来源时间，避免把推送值标成 HTTP 快照时间。 */
export type QuoteUpdate = QuoteData & { as_of: string | null; received_at: string | null };
export type PositionUpdate = PositionData & { as_of: string | null; received_at: string | null };
export type AccountUpdate = AccountData & { as_of: string | null; received_at: string | null };

export type StreamEvent =
  | ({ type: "market.quote.updated"; data: QuoteData } & Envelope)
  | ({ type: "position.updated"; data: PositionData } & Envelope)
  | ({ type: "account.snapshot.updated"; data: AccountData } & Envelope)
  | ({
      type: "data_source.status.updated";
      data: { dataset: string; connected: boolean };
    } & Envelope);

export type StreamState = {
  status: StreamStatus;
  datasets: Record<string, boolean>;
  lastEventAt: string | null;
};

export type StreamLiveness = "live" | "connecting" | "stale";

/** 推送事件和 HTTP 快照都用这一组时间字段判断先后。 */
export type TimedUpdate = {
  as_of: string | null;
  received_at: string | null;
  captured_at?: string | null;
};

export type StreamSubscription = {
  quotes?: readonly string[];
  account?: boolean;
  positions?: boolean;
};

export type SocketLike = Pick<WebSocket, "readyState" | "send" | "close"> & {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
};

export type SocketFactory = (url: string) => SocketLike;

type Normalized = { quotes: string[]; account: boolean; positions: boolean };

const EMPTY: Normalized = { quotes: [], account: false, positions: false };
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 15_000;

function defaultStreamUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}/api/stream`;
}

function defaultSocketFactory(url: string): SocketLike {
  return new WebSocket(url);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

function normalize(subscription: StreamSubscription): Normalized {
  return {
    quotes: [...new Set(subscription.quotes ?? [])].sort(),
    account: subscription.account === true,
    positions: subscription.positions === true,
  };
}

function same(left: Normalized, right: Normalized): boolean {
  return (
    left.account === right.account &&
    left.positions === right.positions &&
    left.quotes.length === right.quotes.length &&
    left.quotes.every((item, index) => item === right.quotes[index])
  );
}

/** 后端只能追加订阅，`outer` 包含 `inner` 时不必重连。 */
function contains(outer: Normalized, inner: Normalized): boolean {
  if (inner.account && !outer.account) return false;
  if (inner.positions && !outer.positions) return false;
  return inner.quotes.every((item) => outer.quotes.includes(item));
}

function parseEnvelope(raw: unknown): Record<string, unknown> | null {
  if (typeof raw !== "string") return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  return isRecord(parsed) && typeof parsed.type === "string" && isRecord(parsed.data)
    ? parsed
    : null;
}

function parseEvent(value: Record<string, unknown>): StreamEvent | null {
  const data = value.data as Record<string, unknown>;
  const asOf = text(value.as_of);
  const receivedAt = text(value.received_at);
  switch (value.type) {
    case "market.quote.updated": {
      const instId = text(data.inst_id);
      if (instId === null) return null;
      return {
        type: "market.quote.updated",
        asOf,
        receivedAt,
        data: {
          inst_id: instId,
          last: text(data.last),
          mark: text(data.mark),
          index: text(data.index),
          source: text(data.source) ?? "unknown",
          stale: data.stale === true,
          snapshot: data.snapshot === true,
        },
      };
    }
    case "position.updated": {
      const posId = text(data.pos_id);
      if (posId === null) return null;
      return {
        type: "position.updated",
        asOf,
        receivedAt,
        data: {
          pos_id: posId,
          inst_id: text(data.inst_id) ?? "",
          display_symbol: text(data.display_symbol),
          name: text(data.name),
          asset_class: text(data.asset_class),
          pos_side: text(data.pos_side),
          size: text(data.size),
          avg_px: text(data.avg_px),
          mark_px: text(data.mark_px),
          upl: text(data.upl),
          upl_ratio: text(data.upl_ratio),
          lever: text(data.lever),
          mgn_mode: text(data.mgn_mode),
          liq_px: text(data.liq_px),
          margin: text(data.margin),
        },
      };
    }
    case "account.snapshot.updated": {
      const accountId = text(data.account_id);
      if (accountId === null) return null;
      return {
        type: "account.snapshot.updated",
        asOf,
        receivedAt,
        data: {
          account_id: accountId,
          currency: text(data.currency),
          equity: text(data.equity),
          available_equity: text(data.available_equity),
          cash_balance: text(data.cash_balance),
          unrealized_pnl: text(data.unrealized_pnl),
          used_margin: text(data.used_margin),
          available_margin: text(data.available_margin),
          margin_usage_pct: text(data.margin_usage_pct),
          captured_at: text(data.captured_at),
          source: text(data.source),
        },
      };
    }
    case "data_source.status.updated": {
      const dataset = text(data.dataset);
      if (dataset === null || typeof data.connected !== "boolean") return null;
      return {
        type: "data_source.status.updated",
        asOf,
        receivedAt,
        data: { dataset, connected: data.connected },
      };
    }
    default:
      return null;
  }
}

export function streamStatusLabel(status: StreamStatus): string {
  if (status === "connected") return "已连接";
  if (status === "connecting") return "连接中";
  if (status === "reconnecting") return "重连中";
  return "未连接";
}

export function updateTime(value: TimedUpdate): string | null {
  return value.captured_at ?? value.as_of ?? value.received_at;
}

/** 时间缺失时不做拒绝，避免因为没有时间字段丢掉实时值。 */
export function isAtLeast(time: string | null, reference: string | null): boolean {
  return time === null || reference === null || time >= reference;
}

export function acceptsUpdate(next: TimedUpdate, current: TimedUpdate | undefined): boolean {
  if (current === undefined) return true;
  return isAtLeast(updateTime(next), updateTime(current));
}

/**
 * 连接层与上游数据源都就绪才算实时。
 * 数据源状态还没到达时不提前判陈旧，避免订阅后短暂闪出「已断开」。
 */
export function streamLiveness(state: StreamState, dataset: StreamDataset): StreamLiveness {
  if (state.status === "idle") return "connecting";
  const datasetConnected = state.datasets[dataset];
  if (state.status === "connected" && datasetConnected !== false) return "live";
  if (state.status === "connecting" && datasetConnected !== false) return "connecting";
  return "stale";
}

export class StreamClient {
  private readonly url: () => string;
  private readonly socketFactory: SocketFactory;
  private socket: SocketLike | null = null;
  private started = false;
  private reconnectAttempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private desired: Normalized = EMPTY;
  private applied: Normalized = EMPTY;
  private owner: symbol | null = null;
  private state: StreamState = { status: "idle", datasets: {}, lastEventAt: null };
  private readonly stateListeners = new Set<() => void>();
  private readonly eventListeners = new Set<(event: StreamEvent) => void>();

  constructor(options: { url?: () => string; socketFactory?: SocketFactory } = {}) {
    this.url = options.url ?? defaultStreamUrl;
    this.socketFactory = options.socketFactory ?? defaultSocketFactory;
  }

  getState = (): StreamState => this.state;

  subscribeState = (listener: () => void): (() => void) => {
    this.stateListeners.add(listener);
    return () => {
      this.stateListeners.delete(listener);
    };
  };

  subscribeEvents = (listener: (event: StreamEvent) => void): (() => void) => {
    this.eventListeners.add(listener);
    return () => {
      this.eventListeners.delete(listener);
    };
  };

  start(): void {
    if (this.started) return;
    this.started = true;
    this.reconnectAttempt = 0;
    this.open("connecting");
  }

  stop(): void {
    this.started = false;
    this.reconnectAttempt = 0;
    this.desired = EMPTY;
    this.applied = EMPTY;
    this.owner = null;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.disposeSocket();
    this.setState({ status: "disconnected", datasets: {} });
  }

  /** 一个页面只保留一个订阅者；`owner` 用来避免旧页面卸载时清掉新页面的订阅。 */
  setSubscription(owner: symbol, subscription: StreamSubscription): void {
    this.owner = owner;
    this.applySubscription(normalize(subscription));
  }

  clearSubscription(owner: symbol): void {
    if (this.owner !== owner) return;
    this.owner = null;
    this.applySubscription(EMPTY);
  }

  private applySubscription(next: Normalized): void {
    if (same(next, this.desired)) return;
    this.desired = next;
    if (this.socket === null || this.socket.readyState !== 1) return;
    if (contains(next, this.applied)) {
      this.sendSubscription(next);
      return;
    }
    // 协议没有退订消息：重建连接，旧订阅随之失效。
    this.reconnectAttempt = 0;
    this.disposeSocket();
    this.open("connecting");
  }

  private open(status: StreamStatus): void {
    if (!this.started) return;
    this.applied = EMPTY;
    this.setState({ status });
    let socket: SocketLike;
    try {
      socket = this.socketFactory(this.url());
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      if (this.socket !== socket) return;
      this.reconnectAttempt = 0;
      this.setState({ status: "connected" });
      this.sendSubscription(this.desired);
    };
    socket.onmessage = (event) => {
      if (this.socket !== socket) return;
      this.handleMessage(event);
    };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      this.socket = null;
      this.scheduleReconnect();
    };
    // onerror 之后浏览器仍会触发 onclose，重连只在 onclose 里安排，避免两次。
    socket.onerror = () => undefined;
  }

  private scheduleReconnect(): void {
    if (!this.started) {
      this.setState({ status: "disconnected" });
      return;
    }
    this.setState({ status: "reconnecting" });
    if (this.timer !== null) return;
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** this.reconnectAttempt, RECONNECT_MAX_MS);
    this.reconnectAttempt += 1;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.open("reconnecting");
    }, delay);
  }

  private disposeSocket(): void {
    const socket = this.socket;
    this.socket = null;
    if (socket === null) return;
    socket.onopen = null;
    socket.onmessage = null;
    socket.onclose = null;
    socket.onerror = null;
    try {
      socket.close();
    } catch {
      // 已关闭或浏览器拒绝关闭时没有可做的补救，下次连接会重新建立。
    }
  }

  private sendSubscription(subscription: Normalized): void {
    const topics: Array<Record<string, unknown>> = [];
    if (subscription.quotes.length > 0) {
      topics.push({ type: "quote", inst_ids: subscription.quotes });
    }
    if (subscription.account) topics.push({ type: "account" });
    if (subscription.positions) topics.push({ type: "positions" });
    this.applied = subscription;
    if (topics.length === 0 || this.socket === null || this.socket.readyState !== 1) return;
    this.socket.send(JSON.stringify({ action: "subscribe", topics }));
  }

  private handleMessage(event: MessageEvent): void {
    const envelope = parseEnvelope(event.data);
    if (envelope === null) return;
    const parsed = parseEvent(envelope);
    if (parsed === null) return;

    if (parsed.type === "data_source.status.updated") {
      this.setState({
        datasets: { ...this.state.datasets, [parsed.data.dataset]: parsed.data.connected },
      });
    } else {
      this.setState({ lastEventAt: parsed.receivedAt ?? parsed.asOf ?? new Date().toISOString() });
    }
    for (const listener of this.eventListeners) listener(parsed);
  }

  private setState(patch: Partial<StreamState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.stateListeners) listener();
  }
}

/** 应用内共享一条推送连接；顶栏读它的状态，页面向它登记订阅。 */
export const streamClient = new StreamClient();
