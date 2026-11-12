/**
 * 后端 HTTP 客户端。
 *
 * 业务端点的请求与响应类型一律取自生成的 `src/api/types.ts`，
 * 这里只做路径拼接与错误归一，不重复声明契约里已有的形状。
 */

import type { components } from "../api/types";

const BASE = "/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type Health = {
  status: "ok";
  version: string;
  env: string;
};

export type WatchlistResponse = components["schemas"]["WatchlistResponse"];
export type WatchlistItem = components["schemas"]["WatchlistItem"];
export type InstrumentDetailResponse = components["schemas"]["InstrumentDetailResponse"];
export type CandleSeriesResponse = components["schemas"]["CandleSeriesResponse"];
export type CandleBar = CandleSeriesResponse["bar"];
export type RelationGraphResponse = components["schemas"]["RelationGraphResponse"];
export type RelationNode = components["schemas"]["RelationNode"];
export type RelationEdge = components["schemas"]["RelationEdge"];
export type IndicatorSeries = components["schemas"]["IndicatorSeries"];
export type IndicatorSeriesResponse = components["schemas"]["IndicatorSeriesResponse"];
export type IndicatorParamValue = IndicatorSeries["params"][string];
export type StrategyCatalogResponse = components["schemas"]["StrategyCatalogResponse"];
export type StrategyDefinition = components["schemas"]["StrategyDefinition"];
export type StrategyParamSpec = StrategyDefinition["params"][number];
export type StrategyParamValue = StrategyDefinition["params"][number]["default"];
export type StrategyInstance = components["schemas"]["StrategyInstance"];
export type StrategyInstanceListResponse = components["schemas"]["StrategyInstanceListResponse"];
export type StrategyInstanceCreateRequest = components["schemas"]["StrategyInstanceCreateRequest"];
export type StrategyInstanceUpdateRequest = components["schemas"]["StrategyInstanceUpdateRequest"];
export type StrategyReplay = components["schemas"]["StrategyReplay"];
export type StrategyReplayListResponse = components["schemas"]["StrategyReplayListResponse"];
export type StrategyReplayPoint = StrategyReplay["points"][number];
export type BacktestRunSummary = components["schemas"]["BacktestRunSummary"];
export type BacktestRunListResponse = components["schemas"]["BacktestRunListResponse"];
export type BacktestRankingResponse = components["schemas"]["BacktestRankingResponse"];
export type BacktestRankingRow = BacktestRankingResponse["items"][number];
export type BacktestMetric = BacktestRankingResponse["metric"];
export type BacktestDataSource = BacktestRunSummary["data_source"];
export type BacktestDetailResponse = components["schemas"]["BacktestDetailResponse"];
export type BacktestLeg = BacktestDetailResponse["legs"][number];
export type BacktestTradeRow = BacktestDetailResponse["trades"][number];
export type BacktestRequest = components["schemas"]["BacktestRequest"];
export type BacktestTargets = components["schemas"]["BacktestTargets"];
export type BacktestCosts = components["schemas"]["BacktestCosts"];
export type BacktestMetrics = components["schemas"]["BacktestMetrics"];
export type ExposureOverviewResponse = components["schemas"]["ExposureOverviewResponse"];
export type PortfolioConflict = components["schemas"]["PortfolioConflict"];
export type StrategyPortfolio = components["schemas"]["StrategyPortfolio"];
export type StrategyPortfolioListResponse = components["schemas"]["StrategyPortfolioListResponse"];
export type StrategyPortfolioDetailResponse =
  components["schemas"]["StrategyPortfolioDetailResponse"];
export type VirtualPosition = components["schemas"]["VirtualPosition"];
export type TargetPortfolio = components["schemas"]["TargetPortfolio"];
export type TargetLeg = components["schemas"]["TargetLeg"];
export type PortfolioAdjustment = components["schemas"]["PortfolioAdjustment"];
export type PortfolioAdjustmentListResponse =
  components["schemas"]["PortfolioAdjustmentListResponse"];
export type PortfolioAdjustmentCreateRequest =
  components["schemas"]["PortfolioAdjustmentCreateRequest"];
export type PortfolioAdjustmentDecisionRequest =
  components["schemas"]["PortfolioAdjustmentDecisionRequest"];

/** 后端错误体的形状：`detail` 是字符串，或 FastAPI 校验错误的条目数组。 */
type ErrorBody = { detail?: string | Array<{ msg?: string }> };

async function failureMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as ErrorBody;
    if (typeof body.detail === "string" && body.detail.trim() !== "") return body.detail;
    if (Array.isArray(body.detail)) {
      const reasons = body.detail
        .map((item) => item.msg ?? "")
        .filter((msg) => msg !== "");
      if (reasons.length > 0) return reasons.join("；");
    }
  } catch {
    // 响应体不是 JSON（例如网关错误页）：回落到状态码文案。
  }
  return `请求失败（HTTP ${response.status}）`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { accept: "application/json", ...init?.headers },
  });
  if (!response.ok) {
    throw new ApiError(response.status, await failureMessage(response));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function send<T>(path: string, method: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function fetchHealth(): Promise<Health> {
  return request<Health>("/health");
}

export function fetchWatchlist(): Promise<WatchlistResponse> {
  return request<WatchlistResponse>("/watchlist");
}

export function fetchInstrumentDetail(instId: string): Promise<InstrumentDetailResponse> {
  return request<InstrumentDetailResponse>(`/instruments/${encodeURIComponent(instId)}`);
}

/** 详情页读的是标的自身在 OKX 的行情：现货与永续是两条来源，按形态取值。 */
export function okxCandleSource(instType: "SPOT" | "SWAP"): "okx_spot" | "okx_swap" {
  return instType === "SWAP" ? "okx_swap" : "okx_spot";
}

/** K 线必须显式带来源：同一标的可能同时存有 OKX 与美股代理两条行情。 */
export function fetchCandles(
  instId: string,
  bar: CandleBar,
  source: "okx" | "okx_spot" | "okx_swap" | "us_equity_proxy",
  limit?: number,
): Promise<CandleSeriesResponse> {
  const query = new URLSearchParams({ bar, source });
  if (limit !== undefined) query.set("limit", String(limit));
  return request<CandleSeriesResponse>(
    `/instruments/${encodeURIComponent(instId)}/candles?${query.toString()}`,
  );
}

export function fetchIndicatorSeries(
  instId: string,
  bar: CandleBar,
  names: string[],
  params?: Record<string, Record<string, IndicatorParamValue>>,
): Promise<IndicatorSeriesResponse> {
  const query = new URLSearchParams({
    inst_id: instId,
    bar,
    names: names.join(","),
  });
  if (params && Object.keys(params).length > 0) query.set("params", JSON.stringify(params));
  return request<IndicatorSeriesResponse>(`/indicators/series?${query.toString()}`);
}

export function fetchRelationGraph(
  bar: CandleBar,
  window: number,
  minAbsCorr: number,
): Promise<RelationGraphResponse> {
  const query = new URLSearchParams({
    bar,
    window: String(window),
    min_abs_corr: String(minAbsCorr),
  });
  return request<RelationGraphResponse>(`/relations/graph?${query.toString()}`);
}


export function fetchStrategies(): Promise<StrategyCatalogResponse> {
  return request<StrategyCatalogResponse>("/strategies");
}

export function fetchStrategyInstances(): Promise<StrategyInstanceListResponse> {
  return request<StrategyInstanceListResponse>("/strategy-instances");
}

export function createStrategyInstance(
  body: StrategyInstanceCreateRequest,
): Promise<StrategyInstance> {
  return send<StrategyInstance>("/strategy-instances", "POST", body);
}

export function updateStrategyInstance(
  instanceId: string,
  body: StrategyInstanceUpdateRequest,
): Promise<StrategyInstance> {
  return send<StrategyInstance>(
    `/strategy-instances/${encodeURIComponent(instanceId)}`,
    "PATCH",
    body,
  );
}

export function deleteStrategyInstance(instanceId: string): Promise<void> {
  return request<void>(`/strategy-instances/${encodeURIComponent(instanceId)}`, {
    method: "DELETE",
  });
}

/** 回放区间按实例配置的周期跑；`start` / `end` 由页面按用户输入的日期拼成 UTC 时刻。 */
export function replayStrategyInstance(
  instanceId: string,
  start: string,
  end: string,
): Promise<StrategyReplay> {
  return send<StrategyReplay>(
    `/strategy-instances/${encodeURIComponent(instanceId)}/replays`,
    "POST",
    { start, end },
  );
}

export function fetchStrategyReplays(instanceId: string): Promise<StrategyReplayListResponse> {
  return request<StrategyReplayListResponse>(
    `/strategy-instances/${encodeURIComponent(instanceId)}/replays`,
  );
}

/** 发起一次批量回测：每个被选中的标的各落一条运行。 */
export function createBacktest(body: BacktestRequest): Promise<BacktestRunSummary> {
  return send<BacktestRunSummary>("/backtests", "POST", body);
}

/** 该数据源的历史回测，新到旧。数据源必填，不做跨源聚合。 */
export function fetchBacktests(dataSource: BacktestDataSource): Promise<BacktestRunListResponse> {
  return request<BacktestRunListResponse>(`/backtests?data_source=${dataSource}`);
}

export function fetchBacktestRanking(
  dataSource: BacktestDataSource,
  metric: BacktestMetric,
): Promise<BacktestRankingResponse> {
  return request<BacktestRankingResponse>(
    `/backtests/ranking?data_source=${dataSource}&metric=${metric}`,
  );
}

export function fetchBacktest(runId: string): Promise<BacktestDetailResponse> {
  return request<BacktestDetailResponse>(`/backtests/${encodeURIComponent(runId)}`);
}

export function deleteBacktest(runId: string): Promise<void> {
  return request<void>(`/backtests/${encodeURIComponent(runId)}`, { method: "DELETE" });
}

export function fetchPortfolioExposure(): Promise<ExposureOverviewResponse> {
  return request<ExposureOverviewResponse>("/portfolio/exposure");
}

export function fetchStrategyPortfolios(): Promise<StrategyPortfolioListResponse> {
  return request<StrategyPortfolioListResponse>("/portfolio/strategies");
}

export function fetchStrategyPortfolio(
  instanceId: string,
): Promise<StrategyPortfolioDetailResponse> {
  return request<StrategyPortfolioDetailResponse>(
    `/portfolio/strategies/${encodeURIComponent(instanceId)}`,
  );
}

export function fetchPortfolioAdjustments(): Promise<PortfolioAdjustmentListResponse> {
  return request<PortfolioAdjustmentListResponse>("/portfolio/adjustments");
}

export function createPortfolioAdjustment(
  body: PortfolioAdjustmentCreateRequest,
): Promise<PortfolioAdjustment> {
  return send<PortfolioAdjustment>("/portfolio/adjustments", "POST", body);
}

export function decidePortfolioAdjustment(
  adjustmentId: string,
  body: PortfolioAdjustmentDecisionRequest,
): Promise<PortfolioAdjustment> {
  return send<PortfolioAdjustment>(
    `/portfolio/adjustments/${encodeURIComponent(adjustmentId)}`,
    "PATCH",
    body,
  );
}
