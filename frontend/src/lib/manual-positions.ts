/**
 * 手动持仓的客户端与展示文案。
 *
 * 数量、成本、市值与盈亏全部由后端计算并返回字符串；这里只做请求封装、标签映射
 * 与正负号补齐，不在前端重算加权成本、已实现盈亏或市值。
 */

import type { components } from "../api/types";
import { request } from "./api";
import { signedValue } from "./display";

export type ManualPosition = components["schemas"]["ManualPositionItem"];
export type ManualPositionList = components["schemas"]["ManualPositionListResponse"];
export type ManualPositionCreateRequest =
  components["schemas"]["ManualPositionCreateRequest"];
export type ManualPositionUpdateRequest =
  components["schemas"]["ManualPositionUpdateRequest"];
export type ManualTrade = components["schemas"]["ManualTradeItem"];
export type ManualTradeList = components["schemas"]["ManualTradeListResponse"];
export type ManualTradeRequest = components["schemas"]["ManualTradeRequest"];
export type ManualTradeAction = ManualTradeRequest["action"];

export const MISSING_VALUE = "未提供";
export const NO_QUOTE_TEXT = "无行情源";

function send<T>(path: string, method: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function fetchManualPositions(): Promise<ManualPositionList> {
  return request<ManualPositionList>("/manual-positions");
}

export function createManualPosition(
  body: ManualPositionCreateRequest,
): Promise<ManualPosition> {
  return send<ManualPosition>("/manual-positions", "POST", body);
}

export function updateManualPosition(
  positionId: string,
  body: ManualPositionUpdateRequest,
): Promise<ManualPosition> {
  return send<ManualPosition>(
    `/manual-positions/${encodeURIComponent(positionId)}`,
    "PATCH",
    body,
  );
}

export function deleteManualPosition(positionId: string): Promise<void> {
  return request<void>(`/manual-positions/${encodeURIComponent(positionId)}`, {
    method: "DELETE",
  });
}

export function fetchManualTrades(positionId: string): Promise<ManualTradeList> {
  return request<ManualTradeList>(
    `/manual-positions/${encodeURIComponent(positionId)}/trades`,
  );
}

export function addManualTrade(
  positionId: string,
  body: ManualTradeRequest,
): Promise<ManualTrade> {
  return send<ManualTrade>(
    `/manual-positions/${encodeURIComponent(positionId)}/trades`,
    "POST",
    body,
  );
}

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

export function sideLabel(side: ManualPosition["side"]): string {
  return side === "short" ? "空" : "多";
}

export function positionStatusLabel(status: ManualPosition["status"]): string {
  return status === "closed" ? "已平仓" : "持仓中";
}

export function actionLabel(action: ManualTrade["action"]): string {
  if (action === "open") return "开仓";
  if (action === "add") return "加仓";
  if (action === "reduce") return "减仓";
  if (action === "close") return "清仓";
  return "更正";
}

export function priceSourceLabel(source: ManualPosition["price_source"]): string {
  if (source === "okx_spot") return "OKX 现货";
  if (source === "okx_swap") return "OKX 永续";
  if (source === "us_equity_proxy") return "美股代理行情";
  if (source === "okx") return "OKX";
  return MISSING_VALUE;
}

function present(value: string | null | undefined): boolean {
  return value !== null && value !== undefined && value.trim() !== "";
}

/** 价格、市值、来源与盈亏都受 `price_status` 约束：没有行情时写“无行情源”。 */
export function quoteText(
  position: ManualPosition,
  value: string | null | undefined,
): string {
  if (position.price_status === "unavailable") return NO_QUOTE_TEXT;
  return present(value) ? (value as string) : MISSING_VALUE;
}

export function quotePnlText(
  position: ManualPosition,
  value: string | null | undefined,
): string {
  if (position.price_status === "unavailable") return NO_QUOTE_TEXT;
  return present(value) ? signedValue(value as string) : MISSING_VALUE;
}

export function quoteSourceText(position: ManualPosition): string {
  if (position.price_status === "unavailable") return NO_QUOTE_TEXT;
  return priceSourceLabel(position.price_source);
}

/** 流水里的已实现盈亏同样由后端算好，页面只补正负号。 */
export function tradePnlText(value: string | null | undefined): string {
  return present(value) ? signedValue(value as string) : MISSING_VALUE;
}

export type CreatePositionFields = {
  instId: string;
  side: ManualPosition["side"];
  quantity: string;
  avgCost: string;
  stopPx: string;
  leverage: string;
  note: string;
};

export function buildCreatePayload(
  fields: CreatePositionFields,
  idempotencyKey: string,
): ManualPositionCreateRequest {
  return {
    inst_id: fields.instId.trim(),
    side: fields.side,
    quantity: fields.quantity.trim(),
    avg_cost: fields.avgCost.trim(),
    stop_px: optionalText(fields.stopPx),
    leverage: optionalText(fields.leverage),
    note: optionalText(fields.note),
    idempotency_key: idempotencyKey,
  };
}

export type UpdatePositionFields = {
  stopPx: string;
  leverage: string;
  note: string;
};

/** 空输入提交为 `null`，这样页面可以清空止损价、杠杆和备注。 */
export function buildUpdatePayload(
  fields: UpdatePositionFields,
): ManualPositionUpdateRequest {
  return {
    stop_px: optionalText(fields.stopPx),
    leverage: optionalText(fields.leverage),
    note: optionalText(fields.note),
  };
}

export type TradeFields = {
  action: ManualTradeAction;
  quantity: string;
  price: string;
  fee: string;
  occurredAt: string;
  note: string;
};

/** 后端的成交时刻要求带时区，表单的本地时间在这里转成 UTC。 */
export function localDateTimeToIso(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toISOString();
}

/** `datetime-local` 输入框需要的本地时间文本。 */
export function localDateTimeValue(date: Date): string {
  const pad = (part: number) => String(part).padStart(2, "0");
  return [
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    `${pad(date.getHours())}:${pad(date.getMinutes())}`,
  ].join("T");
}

export function buildTradePayload(
  fields: TradeFields,
  idempotencyKey: string,
): ManualTradeRequest {
  return {
    action: fields.action,
    quantity: fields.quantity.trim(),
    price: fields.price.trim(),
    fee: fields.action === "correct" ? "0" : (optionalText(fields.fee) ?? "0"),
    occurred_at: localDateTimeToIso(fields.occurredAt),
    note: optionalText(fields.note),
    idempotency_key: idempotencyKey,
  };
}

/** 每次创建、买卖或编辑都带幂等键；重复提交同一键不会重复入账。 */
export function newIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}
