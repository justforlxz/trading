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

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(response.status, `请求失败（HTTP ${response.status}）`);
  }
  return (await response.json()) as T;
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
