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
export type WatchlistStrategy = components["schemas"]["WatchlistStrategy"];
export type InstrumentRef = components["schemas"]["InstrumentRef"];
export type InstrumentSearchResponse = components["schemas"]["InstrumentSearchResponse"];
export type InstrumentDetailResponse = components["schemas"]["InstrumentDetailResponse"];
export type InstrumentAnalysisResponse = components["schemas"]["InstrumentAnalysisResponse"];
export type InstrumentAnalysisQuote = InstrumentAnalysisResponse["quote"];
export type InstrumentAnalysisPrice = NonNullable<InstrumentAnalysisQuote["last"]>;
export type InstrumentAnalysisCandles = InstrumentAnalysisResponse["candles"];
export type InstrumentAnalysisCandle = InstrumentAnalysisCandles["candles"][number];
export type InstrumentAnalysisOverlay = InstrumentAnalysisCandles["overlays"][number];
export type InstrumentAnalysisIndicators = InstrumentAnalysisResponse["indicators"];
export type InstrumentAnalysisLevels = InstrumentAnalysisResponse["levels"];
export type InstrumentAnalysisCorrelation = InstrumentAnalysisResponse["correlations"][number];
export type InstrumentAnalysisLinkedBacktest =
  InstrumentAnalysisResponse["linked_strategies"][number];
export type InstrumentAnalysisCoverage = InstrumentAnalysisResponse["coverage"][number];
export type InstrumentAnalysisBar = InstrumentAnalysisResponse["bar"];
export type CandleSeriesResponse = components["schemas"]["CandleSeriesResponse"];
export type CandleBar = CandleSeriesResponse["bar"];
export type IndicatorSeries = components["schemas"]["IndicatorSeries"];
export type IndicatorSeriesResponse = components["schemas"]["IndicatorSeriesResponse"];
export type IndicatorParamValue = IndicatorSeries["params"][string];
export type StrategySummary = components["schemas"]["StrategySummary"];
export type StrategyListResponse = components["schemas"]["StrategyListResponse"];
export type StrategyDetail = components["schemas"]["StrategyDetail"];
export type StrategyVersionDetail = components["schemas"]["StrategyVersionDetail"];
export type StrategyCreateRequest = components["schemas"]["StrategyCreateRequest"];
export type StrategyUpdateRequest = components["schemas"]["StrategyUpdateRequest"];
export type StrategyVersionCreateRequest = components["schemas"]["StrategyVersionCreateRequest"];
export type StrategyInstrumentUpdateRequest =
  components["schemas"]["StrategyInstrumentUpdateRequest"];
export type StrategyCreatedResponse = components["schemas"]["StrategyCreatedResponse"];
export type StrategyUpdatedResponse = components["schemas"]["StrategyUpdatedResponse"];
export type StrategyVersionListResponse = components["schemas"]["StrategyVersionListResponse"];
export type StrategyBacktestSummary = components["schemas"]["StrategyBacktestSummary"];
export type InstrumentStrategy = components["schemas"]["InstrumentStrategy"];
export type InstrumentStrategyListResponse =
  components["schemas"]["InstrumentStrategyListResponse"];
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
export type BacktestBatchResponse = components["schemas"]["BacktestBatchResponse"];
export type BacktestTargets = components["schemas"]["BacktestTargets"];
export type BacktestCosts = components["schemas"]["BacktestCosts"];
export type BacktestMetrics = components["schemas"]["BacktestMetrics"];
export type SettingsResponse = components["schemas"]["SettingsResponse"];
export type SettingsUpdateRequest = components["schemas"]["SettingsUpdateRequest"];
export type ExecutionSettings = SettingsResponse["execution"];
export type RiskSettings = SettingsResponse["risk"];
export type CostSettings = SettingsResponse["costs"];
export type BacktestSettings = SettingsResponse["backtest"];
export type DataSettings = SettingsResponse["data"];
export type ExchangeSettings = SettingsResponse["exchange"];
export type MarketOverviewResponse = components["schemas"]["MarketOverviewResponse"];

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

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
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

/** 某一类别在某一周期上的市场广度与共振；类别没有默认值，必须显式指定。 */
export function fetchMarketOverview(
  instType: "SPOT" | "SWAP",
  bar: "1d" = "1d",
): Promise<MarketOverviewResponse> {
  const query = new URLSearchParams({ inst_type: instType, bar });
  return request<MarketOverviewResponse>(`/market/overview?${query.toString()}`);
}

/** 按代码或产品键搜索已同步的标的；不传形态时两类一起返回。 */
export function searchInstruments(
  query: string,
  instType?: "SPOT" | "SWAP",
): Promise<InstrumentSearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (instType !== undefined) params.set("inst_type", instType);
  return request<InstrumentSearchResponse>(`/instruments/search?${params.toString()}`);
}

export function addWatchlistItem(instId: string, group = "默认"): Promise<WatchlistItem> {
  return send<WatchlistItem>("/watchlist", "POST", { inst_id: instId, group });
}

export function updateWatchlistItem(instId: string, group: string): Promise<WatchlistItem> {
  return send<WatchlistItem>(`/watchlist/${encodeURIComponent(instId)}`, "PATCH", { group });
}

export function removeWatchlistItem(instId: string): Promise<void> {
  return request<void>(`/watchlist/${encodeURIComponent(instId)}`, { method: "DELETE" });
}

export function fetchInstrumentDetail(instId: string): Promise<InstrumentDetailResponse> {
  return request<InstrumentDetailResponse>(`/instruments/${encodeURIComponent(instId)}`);
}

/** 详情页聚合：所有派生值由后端算好，前端只负责展示。 */
export function fetchInstrumentAnalysis(
  instId: string,
  bar: InstrumentAnalysisBar = "1d",
): Promise<InstrumentAnalysisResponse> {
  const query = new URLSearchParams({ bar });
  return request<InstrumentAnalysisResponse>(
    `/instruments/${encodeURIComponent(instId)}/analysis?${query.toString()}`,
  );
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

export function fetchStrategies(): Promise<StrategyListResponse> {
  return request<StrategyListResponse>("/strategies");
}

export function fetchStrategy(strategyId: string): Promise<StrategyDetail> {
  return request<StrategyDetail>(`/strategies/${encodeURIComponent(strategyId)}`);
}

export function createStrategy(body: StrategyCreateRequest): Promise<StrategyCreatedResponse> {
  return send<StrategyCreatedResponse>("/strategies", "POST", body);
}

export function updateStrategy(
  strategyId: string,
  body: StrategyUpdateRequest,
): Promise<StrategyUpdatedResponse> {
  return send<StrategyUpdatedResponse>(
    `/strategies/${encodeURIComponent(strategyId)}`,
    "PUT",
    body,
  );
}

export function fetchStrategyVersions(
  strategyId: string,
): Promise<StrategyVersionListResponse> {
  return request<StrategyVersionListResponse>(
    `/strategies/${encodeURIComponent(strategyId)}/versions`,
  );
}

export function createStrategyVersion(
  strategyId: string,
  body: StrategyVersionCreateRequest,
): Promise<StrategyVersionDetail> {
  return send<StrategyVersionDetail>(
    `/strategies/${encodeURIComponent(strategyId)}/versions`,
    "POST",
    body,
  );
}

export function replaceStrategyVersionInstruments(
  strategyId: string,
  version: number,
  body: StrategyInstrumentUpdateRequest,
): Promise<StrategyVersionDetail> {
  return send<StrategyVersionDetail>(
    `/strategies/${encodeURIComponent(strategyId)}/versions/${version}/instruments`,
    "PUT",
    body,
  );
}

export function fetchInstrumentStrategies(
  instId: string,
): Promise<InstrumentStrategyListResponse> {
  return request<InstrumentStrategyListResponse>(
    `/instruments/${encodeURIComponent(instId)}/strategies`,
  );
}

/** 发起一次批量回测：每个被选中的标的各落一条运行，同时返回等权组合净值。 */
export function createBacktest(body: BacktestRequest): Promise<BacktestBatchResponse> {
  return send<BacktestBatchResponse>("/backtests", "POST", body);
}

/** 该数据源的历史回测，新到旧。数据源必填，不做跨源聚合。 */
export function fetchBacktests(
  dataSource: BacktestDataSource,
  limit?: number,
): Promise<BacktestRunListResponse> {
  const query = new URLSearchParams({ data_source: dataSource });
  if (limit !== undefined) query.set("limit", String(limit));
  return request<BacktestRunListResponse>(`/backtests?${query.toString()}`);
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

/** 设置文档：分组配置、凭证状态与执行模式。API Key 只写不读。 */
export function fetchSettings(): Promise<SettingsResponse> {
  return request<SettingsResponse>("/settings");
}

export function updateSettings(body: SettingsUpdateRequest): Promise<SettingsResponse> {
  return send<SettingsResponse>("/settings", "PUT", body);
}
