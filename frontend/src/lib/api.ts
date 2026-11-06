/**
 * `/api/v1` 的类型化访问层：只做 HTTP 与 JSON 编解码，不做任何业务计算。
 *
 * 后端错误统一为 `{error:{code,message,details,request_id}}` 信封，
 * 这里转成 `ApiError` 交给调用方决定如何呈现。
 */

export type Exchange = "XNAS" | "XNYS" | "NYSE_ARCA";
export type CorrelationMethod = "pearson" | "spearman";
export type PriceBasis = "okx_close" | "equity_close";

export type Target = {
  id: number;
  symbol: string;
  exchange: Exchange;
  display_name: string | null;
  note: string | null;
  instrument_id: number | null;
  enabled: boolean;
  created_at: string;
};

export type TargetList = {
  items: Target[];
  next_cursor: number | null;
};

export type CreateTargetInput = {
  symbol: string;
  exchange: Exchange;
  display_name?: string | null;
  note?: string | null;
};

export type RelationSnapshot = {
  id: number;
  target_id: number;
  as_of: string;
  window_bars: number;
  method: CorrelationMethod;
  price_basis: PriceBasis;
  lag_max: number;
  sample_size: number;
  run_key: string;
  computed_at: string;
  params: Record<string, unknown>;
};

export type RelationEdge = {
  counterparty_inst_id: string;
  counterparty: {
    symbol: string | null;
    exchange: string | null;
    asset_class: string | null;
  };
  coefficient: string;
  best_lag: number;
  p_value: string | null;
  stability: string | null;
  rank: number;
};

export type RelationChange = {
  counterparty: string;
  kind: "added" | "removed" | "changed";
  previous: number | null;
  current: number | null;
  delta: number | null;
  sign_flip: boolean;
  significant: boolean;
};

export type RelationsPayload = {
  status: "ok" | "undefined";
  reason: string | null;
  snapshot: RelationSnapshot | null;
  edges: RelationEdge[];
  significant_changes: RelationChange[];
};

export type RelationHistoryEntry = RelationSnapshot & {
  edge_count: number;
  significant_changes: RelationChange[];
};

export type RelativeStrengthPoint = {
  ts: string;
  rs_ratio: string | null;
};

export type RelativeStrengthPayload = {
  defined: boolean;
  reason: string | null;
  target: { id: number; symbol: string; exchange: string };
  counterparty: { inst_id: string; symbol: string | null };
  price_basis: PriceBasis;
  lookback_bars: number;
  momentum_bars: number;
  as_of: string | null;
  rs_ratio: string | null;
  rs_momentum: string | null;
  momentum_reason: string | null;
  target_return: string | null;
  counterparty_return: string | null;
  excess_return: string | null;
  trend: "rising" | "falling" | "flat" | null;
  series: RelativeStrengthPoint[];
};

export type RecomputeInput = {
  window_bars: number;
  method: CorrelationMethod;
  price_basis: PriceBasis;
  as_of?: string;
};

export type JobAccepted = {
  job_id: number;
  status: string;
  job_name: string;
  job_key: string;
};

export type JobRun = {
  id: number;
  job_name: string;
  job_key: string;
  status: "queued" | "running" | "ok" | "partial" | "failed" | "skipped";
  attempts: number;
  scheduled_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  worker: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
};

const BASE = "/api/v1";

type ErrorEnvelope = {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
  };
};

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(
    code: string,
    message: string,
    status: number,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const envelope = (payload ?? {}) as ErrorEnvelope;
    throw new ApiError(
      envelope.error?.code ?? `HTTP_${response.status}`,
      envelope.error?.message ?? `请求失败（HTTP ${response.status}）`,
      response.status,
      envelope.error?.details ?? {},
    );
  }

  return payload as T;
}

export async function listTargets(enabled = true): Promise<TargetList> {
  return request<TargetList>(`/targets?enabled=${enabled ? "true" : "false"}&limit=200`);
}

export async function createTarget(input: CreateTargetInput): Promise<Target> {
  return request<Target>("/targets", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateTarget(
  targetId: number,
  input: { display_name?: string | null; note?: string | null },
): Promise<Target> {
  return request<Target>(`/targets/${targetId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

/** 软删除：后端只把 `enabled` 置为 false，不物理删除。 */
export async function deleteTarget(targetId: number): Promise<Target> {
  return request<Target>(`/targets/${targetId}`, { method: "DELETE" });
}

export async function recomputeRelations(
  targetId: number,
  input: RecomputeInput,
): Promise<JobAccepted> {
  return request<JobAccepted>(`/targets/${targetId}/relations/recompute`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function getRelations(
  targetId: number,
  asOf?: string,
): Promise<RelationsPayload> {
  const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
  return request<RelationsPayload>(`/targets/${targetId}/relations${query}`);
}

export async function getRelationHistory(
  targetId: number,
  limit = 20,
): Promise<RelationHistoryEntry[]> {
  const page = await request<{ target_id: number; items: RelationHistoryEntry[] }>(
    `/targets/${targetId}/relations/history?limit=${limit}`,
  );
  return page.items;
}

export async function getRelativeStrength(
  targetId: number,
  input: { counterparty: string; lookback: number; priceBasis: PriceBasis },
): Promise<RelativeStrengthPayload> {
  const params = new URLSearchParams({
    counterparty: input.counterparty,
    lookback: String(input.lookback),
    price_basis: input.priceBasis,
  });
  return request<RelativeStrengthPayload>(
    `/targets/${targetId}/relative-strength?${params.toString()}`,
  );
}

export async function getJobRun(jobId: number): Promise<JobRun> {
  return request<JobRun>(`/ops/job-runs/${jobId}`);
}

const TERMINAL_JOB_STATUSES = new Set(["ok", "partial", "failed", "skipped"]);

/**
 * 等待后台任务结束（观测用，不替代后端账本）。
 *
 * 只轮询 `ops/job-runs/{id}` 的真实状态；超时返回最后一次读到的记录，
 * 不伪造成功，由调用方呈现。
 */
export async function waitForJob(
  jobId: number,
  { attempts = 30, intervalMs = 1000 } = {},
): Promise<JobRun> {
  let latest = await getJobRun(jobId);
  for (let attempt = 1; attempt < attempts; attempt += 1) {
    if (TERMINAL_JOB_STATUSES.has(latest.status)) {
      return latest;
    }
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
    latest = await getJobRun(jobId);
  }
  return latest;
}
