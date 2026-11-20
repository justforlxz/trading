/**
 * 后端 HTTP 客户端。
 *
 * 业务端点的请求与响应类型一律取自生成的 `src/api/types.ts`，
 * 这里只做路径拼接与错误归一，不重复声明契约里已有的形状。
 */

import type { components } from "../api/types";
import { activityQuery, type ActivityFilters } from "./activity";
import { alertListQuery, type AlertFilters, type AlertStatusUpdate } from "./alerts";
import { researchNoteQuery, type ResearchNoteFilters } from "./journal";

const BASE = "/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type WatchlistResponse = components["schemas"]["WatchlistResponse"];
export type WatchlistItem = components["schemas"]["WatchlistItem"];
export type WatchlistStrategy = components["schemas"]["WatchlistStrategy"];
export type InstrumentRef = components["schemas"]["InstrumentRef"];
export type InstrumentListResponse = components["schemas"]["InstrumentListResponse"];
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
export type InstrumentSyncRequest = components["schemas"]["InstrumentSyncRequest"];
export type InstrumentSyncResponse = components["schemas"]["InstrumentSyncResponse"];
export type InstrumentSyncStatus = InstrumentSyncResponse["status"];
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
export type StrategyRuntimeResponse = components["schemas"]["StrategyRuntimeResponse"];
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
export type BacktestChartResponse = components["schemas"]["BacktestChartResponse"];
export type BacktestChartCandle = BacktestChartResponse["candles"][number];
export type BacktestMarker = BacktestChartResponse["markers"][number];
export type BacktestEquityResponse = components["schemas"]["BacktestEquityResponse"];
export type BacktestEquityPoint = BacktestEquityResponse["points"][number];
export type BacktestReplayResponse = components["schemas"]["BacktestReplayResponse"];
export type BacktestReplayPoint = BacktestReplayResponse["points"][number];
export type BacktestReplayTrade = BacktestReplayResponse["trades"][number];
export type BacktestTradeListResponse = components["schemas"]["BacktestTradeListResponse"];
export type BacktestRequest = components["schemas"]["BacktestRequest"];
export type BacktestBatchResponse = components["schemas"]["BacktestBatchResponse"];
export type BacktestTargets = components["schemas"]["BacktestTargets"];
export type BacktestCosts = components["schemas"]["BacktestCosts"];
export type BacktestMetrics = components["schemas"]["BacktestMetrics"];
export type SettingsResponse = components["schemas"]["SettingsResponse"];
export type SettingsUpdateRequest = components["schemas"]["SettingsUpdateRequest"];
export type DisplaySettings = SettingsResponse["display"];
export type ExecutionSettings = SettingsResponse["execution"];
export type RiskDefaults = SettingsResponse["risk_defaults"];
export type DataSourceSettings = SettingsResponse["data_sources"];
export type NotificationSettings = SettingsResponse["notifications"];
export type SecretSettings = SettingsResponse["secrets"];
export type SystemHealthResponse = components["schemas"]["SystemHealthResponse"];
export type SystemComponent = components["schemas"]["SystemComponent"];
export type MarketBreadthResponse = components["schemas"]["MarketBreadthResponse"];
export type MarketSnapshotResponse = components["schemas"]["MarketSnapshotResponse"];
export type MarketOverviewItem = components["schemas"]["MarketOverviewItem"];
export type AiSummaryResponse = components["schemas"]["AiSummaryResponse"];
export type ResearchNoteItem = components["schemas"]["ResearchNoteItem"];
export type ResearchNoteListResponse = components["schemas"]["ResearchNoteListResponse"];
export type ResearchNoteCreateRequest = components["schemas"]["ResearchNoteCreateRequest"];
export type ResearchNoteUpdateRequest = components["schemas"]["ResearchNoteUpdateRequest"];
export type ResearchNoteCreatedResponse = components["schemas"]["ResearchNoteCreatedResponse"];
export type ResearchNoteUpdatedResponse = components["schemas"]["ResearchNoteUpdatedResponse"];
export type AlertListResponse = components["schemas"]["AlertListResponse"];
export type AlertItem = components["schemas"]["AlertItem"];
export type AlertStatusUpdateRequest = components["schemas"]["AlertStatusUpdateRequest"];
export type ActivityListResponse = components["schemas"]["ActivityListResponse"];
export type ActivityItem = components["schemas"]["ActivityItem"];
export type { ResearchNoteFilters, ResearchNoteSort, ResearchNoteType } from "./journal";
export type { ActivityFilters } from "./activity";
export type { AlertFilters, AlertStatusUpdate } from "./alerts";

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
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(
      response.status,
      `请求失败（HTTP ${response.status}，响应不是有效的 JSON）`,
    );
  }
}

function send<T>(path: string, method: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function fetchWatchlist(): Promise<WatchlistResponse> {
  return request<WatchlistResponse>("/watchlist");
}

/** 某一类别的可交易标的；类别必须显式指定，现货与永续不混排。 */
export function fetchTradableInstruments(
  instType: "SPOT" | "SWAP",
): Promise<InstrumentListResponse> {
  const query = new URLSearchParams({ inst_type: instType });
  return request<InstrumentListResponse>(`/instruments?${query.toString()}`);
}

/** 某一类别在某一周期上的市场广度与共振；类别没有默认值，必须显式指定。 */
export function fetchMarketBreadth(
  instType: "SPOT" | "SWAP",
  bar: "1d" = "1d",
): Promise<MarketBreadthResponse> {
  const query = new URLSearchParams({ inst_type: instType, bar });
  return request<MarketBreadthResponse>(`/market/breadth?${query.toString()}`);
}

/** 市场概况只有 BTC 一项；来源是 OKX 公共 ticker，每项自带报价时间与陈旧状态。 */
export function fetchMarketOverview(): Promise<MarketSnapshotResponse> {
  return request<MarketSnapshotResponse>("/market/overview");
}

/** 带来源的市场摘要；只归纳市场概况与待处理提醒，请求没有输入。 */
export function fetchAiSummary(): Promise<AiSummaryResponse> {
  return request<AiSummaryResponse>("/ai/summary", { method: "POST" });
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

/** 请求后台同步当前标的与周期；接口只接受任务，不等待同步完成。 */
export function syncInstrument(
  instId: string,
  bar: InstrumentAnalysisBar,
  days?: number,
): Promise<InstrumentSyncResponse> {
  const body: InstrumentSyncRequest = days === undefined ? { bar } : { bar, days };
  return send<InstrumentSyncResponse>(
    `/instruments/${encodeURIComponent(instId)}/sync`,
    "POST",
    body,
  );
}

/** 详情页读的是标的自身在 OKX 的行情：现货与永续是两条来源，按形态取值。 */
export function okxCandleSource(instType: "SPOT" | "SWAP"): "okx_spot" | "okx_swap" {
  return instType === "SWAP" ? "okx_swap" : "okx_spot";
}

/** K 线必须显式带来源：现货与永续是两条来源。 */
export function fetchCandles(
  instId: string,
  bar: CandleBar,
  source: "okx" | "okx_spot" | "okx_swap",
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

/** 策略页运行状态：信号扫描、自动执行与后端检查时间。 */
export function fetchStrategyRuntime(): Promise<StrategyRuntimeResponse> {
  return request<StrategyRuntimeResponse>("/strategies/runtime");
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

export type BacktestTradeFilters = {
  side?: "long" | "short";
  result?: "profit" | "loss";
  instId?: string;
};

function tradeQuery(filters: BacktestTradeFilters): URLSearchParams {
  const query = new URLSearchParams();
  if (filters.side !== undefined) query.set("side", filters.side);
  if (filters.result !== undefined) query.set("result", filters.result);
  if (filters.instId !== undefined) query.set("inst_id", filters.instId);
  return query;
}

/** 本次回测保存的 K 线、买卖标记与均线叠加；不访问实时行情。 */
export function fetchBacktestChart(runId: string): Promise<BacktestChartResponse> {
  return request<BacktestChartResponse>(`/backtests/${encodeURIComponent(runId)}/chart`);
}

/** 策略净值与回撤序列；基准未保存时 `benchmark` 为 null。 */
export function fetchBacktestEquity(runId: string): Promise<BacktestEquityResponse> {
  return request<BacktestEquityResponse>(`/backtests/${encodeURIComponent(runId)}/equity`);
}

/** 已保存的回放序列；播放与单步只在这个数组里移动，不请求任何行情。 */
export function fetchBacktestReplay(runId: string): Promise<BacktestReplayResponse> {
  return request<BacktestReplayResponse>(`/backtests/${encodeURIComponent(runId)}/replay`);
}

/** 按方向与盈亏结果筛选的交易明细；分页参数原样交给后端。 */
export function fetchBacktestTrades(
  runId: string,
  filters: BacktestTradeFilters = {},
  limit = 500,
  offset = 0,
): Promise<BacktestTradeListResponse> {
  const query = tradeQuery(filters);
  query.set("limit", String(limit));
  query.set("offset", String(offset));
  return request<BacktestTradeListResponse>(
    `/backtests/${encodeURIComponent(runId)}/trades?${query.toString()}`,
  );
}

/** 与表格同筛选条件的 CSV 原文；日期筛选由调用方按同一规则再裁剪。 */
export async function fetchBacktestTradesCsv(
  runId: string,
  filters: BacktestTradeFilters = {},
): Promise<string> {
  const query = tradeQuery(filters);
  const suffix = query.toString();
  const response = await fetch(
    `${BASE}/backtests/${encodeURIComponent(runId)}/trades.csv${suffix === "" ? "" : `?${suffix}`}`,
    { headers: { accept: "text/csv" } },
  );
  if (!response.ok) {
    throw new ApiError(response.status, await failureMessage(response));
  }
  return response.text();
}

export function deleteBacktest(runId: string): Promise<void> {
  return request<void>(`/backtests/${encodeURIComponent(runId)}`, { method: "DELETE" });
}

/** 研究记录列表：筛选、排序与游标全部交给后端，前端只决定页码大小。 */
export function fetchResearchNotes(
  filters: ResearchNoteFilters = {},
  limit = 200,
  cursor?: string,
): Promise<ResearchNoteListResponse> {
  const query = researchNoteQuery(filters);
  query.set("limit", String(limit));
  if (cursor !== undefined && cursor !== "") query.set("cursor", cursor);
  return request<ResearchNoteListResponse>(`/research-notes?${query.toString()}`);
}

export function createResearchNote(
  body: ResearchNoteCreateRequest,
): Promise<ResearchNoteCreatedResponse> {
  return send<ResearchNoteCreatedResponse>("/research-notes", "POST", body);
}

export function updateResearchNote(
  noteId: string,
  body: ResearchNoteUpdateRequest,
): Promise<ResearchNoteUpdatedResponse> {
  return send<ResearchNoteUpdatedResponse>(
    `/research-notes/${encodeURIComponent(noteId)}`,
    "PUT",
    body,
  );
}

export function deleteResearchNote(noteId: string): Promise<void> {
  return request<void>(`/research-notes/${encodeURIComponent(noteId)}`, { method: "DELETE" });
}

/** 提醒列表：筛选与游标交给后端；默认只取待处理提醒。 */
export function fetchAlerts(
  filters: AlertFilters = { status: "pending" },
  limit = 50,
  cursor?: string,
): Promise<AlertListResponse> {
  const query = alertListQuery(filters);
  query.set("limit", String(limit));
  if (cursor !== undefined && cursor !== "") query.set("cursor", cursor);
  return request<AlertListResponse>(`/alerts?${query.toString()}`);
}

/** 确认或忽略一条待处理提醒；成功后后端会写一条活动。 */
export function updateAlertStatus(
  alertId: string,
  status: AlertStatusUpdate,
): Promise<AlertItem> {
  return send<AlertItem>(`/alerts/${encodeURIComponent(alertId)}`, "PATCH", { status });
}

/** 活动流水：按时间倒序，筛选与游标全部交给后端。 */
export function fetchActivity(
  filters: ActivityFilters = {},
  limit = 50,
  cursor?: string,
): Promise<ActivityListResponse> {
  const query = activityQuery(filters);
  query.set("limit", String(limit));
  if (cursor !== undefined && cursor !== "") query.set("cursor", cursor);
  return request<ActivityListResponse>(`/activity?${query.toString()}`);
}

/** 设置文档：显示偏好、风险默认值、自动执行开关、数据源与凭证状态。API Key 只写不读。 */
export function fetchSettings(): Promise<SettingsResponse> {
  return request<SettingsResponse>("/settings");
}

export function updateSettings(body: SettingsUpdateRequest): Promise<SettingsResponse> {
  return send<SettingsResponse>("/settings", "PATCH", body);
}

/** 系统健康：六项都来自后端已有事实，页面只展示，不补造时间或推断状态。 */
export function fetchSystemHealth(): Promise<SystemHealthResponse> {
  return request<SystemHealthResponse>("/system/health");
}
