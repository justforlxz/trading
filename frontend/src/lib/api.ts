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

export type OpportunityKind = "directional" | "relative_value";
export type OpportunityDirection = "long" | "short" | "pair";

export type Breadth = {
  up: number;
  down: number;
  flat: number;
  total: number;
  up_ratio: number | null;
  down_ratio: number | null;
};

export type OpportunityEvidenceMember = {
  instrument_id: number;
  inst_id: string;
  symbol: string;
  ret_1d: number | null;
  ret_5d: number | null;
  ret_20d: number | null;
  vol_20d: number | null;
  distance: number;
  correlation: number;
};

export type Opportunity = {
  id: number;
  run_id: number;
  kind: OpportunityKind;
  direction: OpportunityDirection;
  score: string;
  horizon: string;
  reasons: string[];
  evidence: Record<string, unknown>;
  primary_instrument_id: number;
  primary_inst_id: string | null;
  primary_symbol: string | null;
  created_at: string | null;
};

export type OpportunityDetail = Opportunity & { members: OpportunityEvidenceMember[] };

export type OpportunityList = {
  run_id: number | null;
  items: Opportunity[];
  next_cursor: string | null;
};

export type OpportunityRunCounts = {
  universe?: number;
  snapshot?: number;
  missing?: {
    private_company: string[];
    no_candles: string[];
    insufficient_bars: string[];
  };
  clusters?: number;
  undefined_pairs?: number;
  opportunities?: { directional: number; relative_value: number; total: number };
  breadth?: Breadth | null;
  as_of?: string;
  duration_ms?: number;
  bar?: string;
  lookback_bars?: number;
};

export type OpportunityRun = {
  id: number;
  run_key: string;
  as_of: string;
  universe_size: number;
  status: "running" | "ok" | "partial" | "failed";
  started_at: string;
  finished_at: string | null;
  error: string | null;
  params: Record<string, unknown>;
  counts: OpportunityRunCounts;
};

export type ClusterMember = {
  instrument_id: number;
  inst_id: string;
  symbol: string;
  distance: string | null;
  weight: string | null;
};

export type AssetCluster = {
  id: number;
  run_id: number;
  label: string;
  method: string;
  silhouette: string | null;
  size: number;
  centroid: Record<string, unknown>;
  members: ClusterMember[];
};

export type ClusterList = {
  run_id: number | null;
  items: AssetCluster[];
};

export type SnapshotItem = {
  instrument_id: number;
  inst_id: string;
  symbol: string;
  asset_class: string | null;
  ret_1d: string | null;
  ret_5d: string | null;
  ret_20d: string | null;
  vol_20d: string | null;
  atr_14: string | null;
  volume_z: string | null;
  high_20d: string | null;
  low_20d: string | null;
  extras: Record<string, unknown>;
};

export type MarketSession = "PRE" | "REGULAR" | "POST" | "CLOSED";

export type MarketSnapshot = {
  as_of: string | null;
  count: number;
  breadth: Breadth | null;
  session: MarketSession;
  items: SnapshotItem[];
};

export type ScanInput = {
  as_of?: string;
  universe?: string[];
  params?: Record<string, unknown>;
};

export async function scanOpportunities(input: ScanInput = {}): Promise<JobAccepted> {
  return request<JobAccepted>("/opportunities/scan", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function listOpportunities(
  params: {
    run_id?: number;
    kind?: OpportunityKind;
    direction?: OpportunityDirection;
    min_score?: number;
    limit?: number;
    cursor?: string;
  } = {},
): Promise<OpportunityList> {
  const query = new URLSearchParams();
  if (params.run_id !== undefined) query.set("run_id", String(params.run_id));
  if (params.kind) query.set("kind", params.kind);
  if (params.direction) query.set("direction", params.direction);
  if (params.min_score !== undefined) query.set("min_score", String(params.min_score));
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.cursor) query.set("cursor", params.cursor);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<OpportunityList>(`/opportunities${suffix}`);
}

export async function getOpportunity(opportunityId: number): Promise<OpportunityDetail> {
  return request<OpportunityDetail>(`/opportunities/${opportunityId}`);
}

export async function listOpportunityRuns(
  params: { status?: string; limit?: number; cursor?: number } = {},
): Promise<{ items: OpportunityRun[]; next_cursor: number | null }> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.cursor !== undefined) query.set("cursor", String(params.cursor));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<{ items: OpportunityRun[]; next_cursor: number | null }>(
    `/opportunities/runs${suffix}`,
  );
}

export async function getOpportunityRun(runId: number): Promise<OpportunityRun> {
  return request<OpportunityRun>(`/opportunities/runs/${runId}`);
}

export async function listClusters(runId?: number): Promise<ClusterList> {
  const suffix = runId === undefined ? "" : `?run_id=${runId}`;
  return request<ClusterList>(`/clusters${suffix}`);
}

export async function getMarketSnapshot(asOf?: string): Promise<MarketSnapshot> {
  const suffix = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
  return request<MarketSnapshot>(`/market/snapshot${suffix}`);
}

// ---- 策略（S6） -------------------------------------------------------------

export type StrategyKind = "directional" | "relative_value";
export type StrategyStatus =
  | "draft"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "archived";
export type StrategySide = "long" | "short";
export type StrategyApprovalDecision = "approved" | "rejected";

export type StrategyLeg = {
  id: number;
  instrument_id: number;
  inst_id: string;
  symbol: string | null;
  side: StrategySide;
  weight: string;
  rationale: string;
  rank: number;
};

export type StrategyApproval = {
  id: number;
  decision: StrategyApprovalDecision;
  content_hash: string;
  reviewer: string;
  note: string | null;
  decided_at: string;
};

export type StrategyTransition = {
  id: number;
  from_status: StrategyStatus;
  to_status: StrategyStatus;
  at: string;
  actor: string;
  reason: string | null;
  request_id: string | null;
};

export type StrategySource = {
  type: "target" | "opportunity";
  [key: string]: unknown;
};

export type StrategyExclusion = {
  instrument_id: number;
  inst_id: string;
  reason: string;
};

export type Strategy = {
  id: number;
  strategy_key: string;
  name: string;
  kind: StrategyKind;
  status: StrategyStatus;
  target_id: number | null;
  templates: string[];
  params: Record<string, unknown>;
  source: StrategySource | null;
  exclusions: StrategyExclusion[];
  content_hash: string;
  version: number;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
  reviewer: string | null;
  legs: StrategyLeg[];
  approvals?: StrategyApproval[];
  transitions?: StrategyTransition[];
};

export type StrategyList = {
  items: Strategy[];
  next_cursor: string | null;
};

export async function listStrategies(
  params: {
    status?: StrategyStatus;
    kind?: StrategyKind;
    limit?: number;
    cursor?: string;
  } = {},
): Promise<StrategyList> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.kind) query.set("kind", params.kind);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.cursor) query.set("cursor", params.cursor);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<StrategyList>(`/strategies${suffix}`);
}

export async function getStrategy(strategyId: number): Promise<Strategy> {
  return request<Strategy>(`/strategies/${strategyId}`);
}

export async function submitStrategy(strategyId: number): Promise<Strategy> {
  return request<Strategy>(`/strategies/${strategyId}/submit`, { method: "POST" });
}

export async function approveStrategy(
  strategyId: number,
  reviewer: string,
  note?: string,
): Promise<Strategy> {
  return request<Strategy>(`/strategies/${strategyId}/approve`, {
    method: "POST",
    body: JSON.stringify({ reviewer, note: note ?? null }),
  });
}

export async function rejectStrategy(
  strategyId: number,
  reviewer: string,
  note: string,
): Promise<Strategy> {
  return request<Strategy>(`/strategies/${strategyId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reviewer, note }),
  });
}

export async function archiveStrategy(strategyId: number): Promise<Strategy> {
  return request<Strategy>(`/strategies/${strategyId}/archive`, { method: "POST" });
}

// ---- 历史回测（S7） --------------------------------------------------------

export type BacktestStatus = "queued" | "running" | "ok" | "failed";

export type BacktestWindowInput = {
  start: string;
  end: string;
  name?: string;
  role?: "train" | "test" | "eval";
};

export type BacktestCostModel = {
  taker_fee_bps: string;
  maker_fee_bps: string;
  slippage_bps: string;
  funding_bps_per_period: string;
  funding: boolean;
  fee_role: "taker" | "maker";
};

export type BacktestThreshold = {
  name: string;
  op: ">=" | "<=" | ">" | "<" | "==";
  value: string;
};

export type BacktestCriteriaResult = {
  name: string;
  op: string;
  threshold: string;
  actual: string;
  passed: boolean;
};

export type BacktestCriteria = {
  thresholds: BacktestThreshold[];
  results: BacktestCriteriaResult[];
  passed: boolean;
  default: boolean;
};

export type BacktestRun = {
  id: number;
  run_key: string;
  strategy_id: number;
  strategy_version: number;
  window: { start: string; end: string };
  bar: string;
  initial_capital: string;
  cost_model: BacktestCostModel;
  params: Record<string, unknown>;
  criteria: BacktestCriteria | null;
  funding_assumption: string | null;
  status: BacktestStatus;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
};

export type BacktestMetric = {
  name: string;
  value: string;
  unit: string;
};

export type BacktestEquityPoint = {
  ts: string;
  equity: string;
  cash: string;
  exposure: string;
  drawdown: string;
};

export type BacktestTrade = {
  id: number;
  instrument_id: number;
  inst_id: string | null;
  symbol: string | null;
  side: StrategySide;
  entry_ts: string;
  exit_ts: string;
  entry_px: string;
  exit_px: string;
  qty: string;
  gross_pnl: string;
  fees: string;
  funding: string;
  slippage: string;
  net_pnl: string;
  bars_held: number;
  exit_reason: string;
};

export type CreateBacktestInput = {
  strategy_id: number;
  window: BacktestWindowInput;
  windows?: BacktestWindowInput[];
  bar: string;
  initial_capital: string;
  cost_model: Omit<BacktestCostModel, "funding" | "fee_role"> &
    Partial<Pick<BacktestCostModel, "funding" | "fee_role">>;
  criteria?: { thresholds: BacktestThreshold[] };
  risk_free_rate?: string;
  annualization_factor?: string;
};

export type BacktestAccepted = {
  run_id: number;
  job_id: number;
  status: string;
  run_key: string;
  created: boolean;
  dispatched: boolean;
};

export async function createBacktest(input: CreateBacktestInput): Promise<BacktestAccepted> {
  return request<BacktestAccepted>("/backtests", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function getBacktest(runId: number): Promise<BacktestRun> {
  return request<BacktestRun>(`/backtests/${runId}`);
}

export async function getBacktestMetrics(
  runId: number,
): Promise<{ run_id: number; status: string; items: BacktestMetric[] }> {
  return request(`/backtests/${runId}/metrics`);
}

export async function listBacktestEquity(
  runId: number,
  params: { limit?: number; cursor?: string } = {},
): Promise<{ items: BacktestEquityPoint[]; next_cursor: string | null }> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.cursor) query.set("cursor", params.cursor);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/backtests/${runId}/equity${suffix}`);
}

export async function listBacktestTrades(
  runId: number,
  params: { limit?: number; cursor?: number } = {},
): Promise<{ items: BacktestTrade[]; next_cursor: number | null }> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.cursor !== undefined) query.set("cursor", String(params.cursor));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/backtests/${runId}/trades${suffix}`);
}

export type RiskSeverity = "tier1" | "tier2" | "tier3";

export type RiskAction = "none" | "warn" | "reduce" | "close";

export type RiskEventKind = "limit_breach" | "drawdown" | "funding" | "liquidity";

export type RiskThresholds = {
  max_order_notional: string;
  max_leg_weight: string;
  max_leverage: string;
  max_gross_exposure: string;
  max_net_exposure: string;
  max_instrument_weight: string;
  max_concentration: string;
  drawdown_warn: string;
  drawdown_reduce: string;
  drawdown_close: string;
  funding_rate_threshold: string;
  min_depth_notional: string;
};

export type RiskPolicy = {
  scope: "global" | "strategy";
  strategy_id: number | null;
  version: number;
  thresholds: RiskThresholds;
  updated_at: string;
  updated_by: string;
  note: string | null;
};

export type RiskBreach = {
  code: string;
  field: string;
  observed: string;
  threshold: string;
};

export type RiskDuplicateHolding = {
  instrument_id: number;
  side: string;
  strategy_ids: number[];
};

export type RiskStatus = {
  scope: "global" | "strategy";
  strategy_id: number | null;
  policy_version: number;
  allowed: boolean;
  reason: string | null;
  limits: RiskThresholds;
  capital: string | null;
  gross_exposure: string | null;
  net_exposure: string | null;
  leverage: string | null;
  concentration: string | null;
  long_exposure: string | null;
  short_exposure: string | null;
  long_short_conflicts: number[];
  duplicates: RiskDuplicateHolding[];
  breaches: RiskBreach[];
};

export type RiskEventItem = {
  id: number;
  kind: RiskEventKind;
  severity: RiskSeverity;
  action: RiskAction;
  strategy_id: number | null;
  instrument_id: number | null;
  policy_version: number;
  observed_value: string | null;
  threshold: string | null;
  payload: Record<string, unknown>;
  evaluation_key: string;
  created_at: string;
  resolved_at: string | null;
};

export type RiskEventPage = {
  items: RiskEventItem[];
  next_cursor: string | null;
};

export type RiskFundingItem = {
  inst_id: string;
  funding_rate: string;
  next_funding_at: string | null;
  best_bid: string;
  best_ask: string;
  bid_depth: string;
  ask_depth: string;
};

export type RiskFundingBreach = {
  kind: "funding" | "liquidity";
  severity: RiskSeverity;
  action: RiskAction;
  inst_id: string;
  observed_value: string;
  threshold: string;
};

export type RiskFundingReport = {
  items: RiskFundingItem[];
  breaches: RiskFundingBreach[];
  missing: string[];
};

export type UpdateRiskPolicyInput = {
  expected_version: number;
  updated_by: string;
  note?: string | null;
  strategy_id?: number | null;
  thresholds: RiskThresholds;
};

export type RiskEvaluateInput = {
  strategy_id: number;
  as_of?: string | null;
  evaluation_key?: string | null;
};

function riskQuery(params: Record<string, string | number | undefined | null>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  const suffix = query.toString();
  return suffix ? `?${suffix}` : "";
}

export async function getRiskPolicy(strategyId?: number): Promise<RiskPolicy> {
  return request<RiskPolicy>(`/risk/policy${riskQuery({ strategy_id: strategyId })}`);
}

export async function updateRiskPolicy(input: UpdateRiskPolicyInput): Promise<RiskPolicy> {
  return request<RiskPolicy>("/risk/policy", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function getRiskStatus(strategyId?: number): Promise<RiskStatus> {
  return request<RiskStatus>(`/risk/status${riskQuery({ strategy_id: strategyId })}`);
}

export async function listRiskEvents(
  params: {
    kind?: RiskEventKind;
    severity?: RiskSeverity;
    strategy_id?: number;
    since?: string;
    limit?: number;
    cursor?: string;
  } = {},
): Promise<RiskEventPage> {
  return request<RiskEventPage>(`/risk/events${riskQuery(params)}`);
}

export async function getRiskFunding(
  params: { strategy_id?: number; inst_ids?: string } = {},
): Promise<RiskFundingReport> {
  return request<RiskFundingReport>(`/risk/funding${riskQuery(params)}`);
}

export type RiskEvaluateAccepted = {
  run_id: number;
  job_id: number;
  status: string;
  run_key: string;
  created: boolean;
  dispatched: boolean;
};

export async function evaluateRisk(input: RiskEvaluateInput): Promise<RiskEvaluateAccepted> {
  return request<RiskEvaluateAccepted>("/risk/evaluate", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export type AiCitation = {
  type: string;
  source: string;
  [key: string]: unknown;
};

export type AiModelView = {
  provider: string;
  model: string;
};

export type AiQueryResponse = {
  answer: string;
  intent: string | null;
  citations: AiCitation[];
  model: AiModelView;
  degraded: boolean;
  missing?: string[];
  /** 所有 `/ai/*` 200 响应固定为 true。 */
  read_only?: boolean;
  /** false 表示后端拒答（未许可/未识别），此时没有引用、也没有域数据。 */
  answerable?: boolean;
  /** 拒答原因, 取值同后端 `Decision.refusal`。 */
  reason?: string;
};

export type AiQueryInput = {
  question: string;
  limit?: number;
};

/** 只读问答: 写意图由后端拒绝并返回 403 ai_write_forbidden。 */
export async function askAssistant(input: AiQueryInput): Promise<AiQueryResponse> {
  return request<AiQueryResponse>("/ai/query", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
