/**
 * 策略页运行状态的展示文案。
 *
 * 信号扫描与自动执行的取值由 `GET /api/strategies/runtime` 返回；行情订阅只取
 * `/api/stream` 推送层的 `data_source.status.updated`，不从页面连接状态推断。
 */

import type { StrategyRuntimeResponse } from "./api";

export type MarketSubscriptionStatus = "connected" | "disconnected" | "pending";

/** 公共行情通道的推送状态；状态事件尚未到达时保持「等待」，不当作已连接。 */
export function marketSubscriptionStatus(
  datasets: Record<string, boolean>,
): MarketSubscriptionStatus {
  const connected = datasets.public_ws;
  if (connected === true) return "connected";
  if (connected === false) return "disconnected";
  return "pending";
}

export function marketSubscriptionLabel(status: MarketSubscriptionStatus): string {
  if (status === "connected") return "已连接";
  if (status === "disconnected") return "未连接";
  return "等待推送层状态";
}

export function signalScanLabel(scan: StrategyRuntimeResponse["signal_scan"]): string {
  return scan.status === "not_implemented" ? "未实现" : scan.status;
}

export function autoExecutionLabel(auto: StrategyRuntimeResponse["auto_execution"]): string {
  return auto.enabled ? "已开启" : "已关闭";
}
