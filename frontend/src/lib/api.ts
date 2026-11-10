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

export function fetchCandles(
  instId: string,
  bar: CandleBar,
  limit?: number,
): Promise<CandleSeriesResponse> {
  const query = new URLSearchParams({ bar });
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
