/**
 * 策略与回测页的展示辅助。
 *
 * 这里只做标签映射、JSON 文本转换与列表过滤：数值、版本号和时间都保持接口返回的
 * 原值，不在这里重算任何收益、回撤或仓位。
 */

import type {
  BacktestDataSource,
  BacktestRunSummary,
  StrategySummary,
  StrategyVersionDetail,
} from "./api";

export type StrategyStatus = StrategySummary["status"];
export type StrategyDirection = StrategyVersionDetail["direction"];
export type StrategyTimeframe = StrategyVersionDetail["timeframe"];
export type ExecutionModel = "next_open" | "next_close";

export const STRATEGY_CATEGORY_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "directional", label: "方向性（directional）" },
  { value: "relative_value", label: "相对价值（relative_value）" },
];

export const STRATEGY_STATUS_OPTIONS: ReadonlyArray<{ value: StrategyStatus; label: string }> = [
  { value: "draft", label: "草稿" },
  { value: "validated", label: "已验证" },
  { value: "enabled", label: "启用" },
  { value: "paused", label: "暂停" },
  { value: "archived", label: "归档" },
];

export const STRATEGY_DIRECTION_OPTIONS: ReadonlyArray<{
  value: StrategyDirection;
  label: string;
}> = [
  { value: "long_only", label: "只做多" },
  { value: "short_only", label: "只做空" },
  { value: "long_short", label: "多空双向" },
];

export const STRATEGY_TIMEFRAME_OPTIONS: ReadonlyArray<{
  value: StrategyTimeframe;
  label: string;
}> = [
  { value: "1m", label: "1 分钟" },
  { value: "5m", label: "5 分钟" },
  { value: "15m", label: "15 分钟" },
  { value: "1h", label: "1 小时" },
  { value: "4h", label: "4 小时" },
  { value: "1d", label: "1 天" },
];

export const BACKTEST_DATA_SOURCE_OPTIONS: ReadonlyArray<{
  value: BacktestDataSource;
  label: string;
}> = [
  { value: "okx_spot", label: "OKX 现货（okx_spot）" },
  { value: "okx_swap", label: "OKX 永续（okx_swap）" },
  { value: "us_equity_proxy", label: "美股代理（us_equity_proxy）" },
  { value: "okx", label: "未区分形态的旧数据（okx）" },
];

export const EXECUTION_MODEL_OPTIONS: ReadonlyArray<{ value: ExecutionModel; label: string }> = [
  { value: "next_open", label: "下一根 K 线开盘价成交" },
  { value: "next_close", label: "下一根 K 线收盘价成交" },
];

function labelOf<T extends string>(
  options: ReadonlyArray<{ value: T; label: string }>,
  value: T,
): string {
  return options.find((option) => option.value === value)?.label ?? value;
}

export function categoryLabel(value: string): string {
  return STRATEGY_CATEGORY_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function statusLabel(value: StrategyStatus): string {
  return labelOf(STRATEGY_STATUS_OPTIONS, value);
}

export function directionLabel(value: StrategyDirection): string {
  return labelOf(STRATEGY_DIRECTION_OPTIONS, value);
}

export function dataSourceLabel(value: BacktestDataSource): string {
  return labelOf(BACKTEST_DATA_SOURCE_OPTIONS, value);
}

export function versionLabel(version: number): string {
  return `v${version}`;
}

/** 可复现输入按原样展示；空值留空，由调用方写「未设置」。 */
export function prettyJson(value: unknown): string {
  if (value === null || value === undefined) return "";
  return JSON.stringify(value, null, 2) ?? "";
}

/** 表单里的 JSON 对象：拒绝非对象与无效 JSON，错误文案指明是哪个字段。 */
export function parseJsonObject(text: string, label: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (trimmed === "") throw new Error(`${label}不能为空`);
  let value: unknown;
  try {
    value = JSON.parse(trimmed) as unknown;
  } catch {
    throw new Error(`${label}不是有效的 JSON`);
  }
  if (value === null || Array.isArray(value) || typeof value !== "object") {
    throw new Error(`${label}必须是 JSON 对象`);
  }
  return value as Record<string, unknown>;
}

export function parseOptionalJsonObject(
  text: string,
  label: string,
): Record<string, unknown> | null {
  if (text.trim() === "") return null;
  return parseJsonObject(text, label);
}

/** 标的标识按空白或逗号分隔；重复项只保留第一次出现的位置。 */
export function splitInstrumentIds(text: string): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of text.split(/[\s,]+/).map((value) => value.trim())) {
    if (item === "" || seen.has(item)) continue;
    seen.add(item);
    result.push(item);
  }
  return result;
}

export function joinInstrumentIds(ids: readonly string[]): string {
  return ids.join("\n");
}

/** 该策略所有版本的回测记录；接口给的是当前数据源的全量列表，这里只按版本标识过滤。 */
export function backtestsForVersions(
  runs: readonly BacktestRunSummary[],
  versionIds: readonly string[],
): BacktestRunSummary[] {
  const wanted = new Set(versionIds);
  return runs.filter(
    (run) => run.strategy_version_id !== null && wanted.has(run.strategy_version_id),
  );
}

export function parameterRows(
  parameters: Record<string, unknown>,
): Array<{ key: string; value: string }> {
  return Object.entries(parameters)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => ({
      key,
      value: typeof value === "string" ? value : JSON.stringify(value),
    }));
}
