/**
 * 持仓页风险与敞口的只读客户端与展示文案。
 *
 * 所有数值都来自 `GET /api/risk/exposure` 与
 * `PUT /api/positions/{position_ref}/risk-config` 的返回，这里不计算杠杆、
 * ATR 距离、占比或风险等级，只把契约里的字符串原样交给页面。
 */

import type { components } from "../api/types";
import { request } from "./api";

export type RiskExposure = components["schemas"]["RiskExposureResponse"];
export type RiskSummary = RiskExposure["summary"];
export type RiskPosition = RiskExposure["positions"][number];
export type RiskRule = RiskExposure["rules"][number];
export type SectorExposure = RiskExposure["sectors"][number];
export type RiskConfig = components["schemas"]["PositionRiskConfigResponse"];
export type RiskConfigUpdate = components["schemas"]["RiskConfigUpdateRequest"];

export const UNAVAILABLE_TEXT = "不可用";

export type RiskConfigFields = {
  stopPx: string;
  riskBudget: string;
  warningThresholdPct: string;
};

export type RiskLevelView = {
  label: string;
  tone: string;
  available: boolean;
};

export type RiskRuleMeta = {
  label: string;
  inputs: readonly string[];
};

/**
 * 规则 ID 到展示文案和输入字段的映射。输入字段只用于让用户核对规则来源，
 * 不参与任何计算；后端契约目前不返回输入字段，映射缺失的规则显示不可用。
 */
const RISK_RULE_META: Record<string, RiskRuleMeta> = {
  stop_missing: {
    label: "未设置止损",
    inputs: ["stop_px"],
  },
  stop_distance: {
    label: "止损距离不足 1 ATR",
    inputs: ["mark_px", "stop_px", "atr"],
  },
  high_leverage: {
    label: "杠杆超过设置阈值",
    inputs: ["lever", "settings.risk.max_leverage"],
  },
  single_instrument_weight: {
    label: "单标的占比超过设置阈值",
    inputs: [
      "weight_pct",
      "notional",
      "gross_notional",
      "settings.risk.max_single_instrument_weight_pct",
    ],
  },
  margin_usage: {
    label: "保证金使用率超过设置阈值",
    inputs: [
      "margin_usage_pct",
      "used_margin",
      "available_margin",
      "settings.risk.max_margin_usage_pct",
    ],
  },
};

const RISK_LEVEL_VIEWS: Record<"low" | "medium" | "high", RiskLevelView> = {
  low: {
    label: "低",
    tone: "border-emerald-600/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
    available: true,
  },
  medium: {
    label: "中",
    tone: "border-amber-600/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
    available: true,
  },
  high: {
    label: "高",
    tone: "border-rose-600/40 bg-rose-500/10 text-rose-700 dark:text-rose-400",
    available: true,
  },
};

const UNAVAILABLE_TONE = "border-border text-muted-foreground";

export function fetchRiskExposure(): Promise<RiskExposure> {
  return request<unknown>("/risk/exposure").then((payload) => {
    const problem = riskExposureProblem(payload);
    if (problem !== null) throw new Error(problem);
    return payload as RiskExposure;
  });
}

export function riskConfigPath(positionRef: string): string {
  return `/positions/${encodeURIComponent(positionRef)}/risk-config`;
}

export function savePositionRiskConfig(
  positionRef: string,
  body: RiskConfigUpdate,
): Promise<RiskConfig> {
  return request<RiskConfig>(riskConfigPath(positionRef), {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** 只提交填写了的字段；留空表示不修改已保存值，不把空输入当成 0。 */
export function buildRiskConfigPayload(fields: RiskConfigFields): RiskConfigUpdate {
  const payload: RiskConfigUpdate = {};
  const stopPx = fields.stopPx.trim();
  const riskBudget = fields.riskBudget.trim();
  const warningThresholdPct = fields.warningThresholdPct.trim();
  if (stopPx !== "") payload.stop_px = stopPx;
  if (riskBudget !== "") payload.risk_budget = riskBudget;
  if (warningThresholdPct !== "") payload.warning_threshold_pct = warningThresholdPct;
  return payload;
}

export function hasRiskConfigInput(fields: RiskConfigFields): boolean {
  return Object.keys(buildRiskConfigPayload(fields)).length > 0;
}

export function unavailableText(reason: string): string {
  return `${UNAVAILABLE_TEXT}（${reason}）`;
}

export function textOrUnavailable(
  value: string | null | undefined,
  reason = "后端未返回该字段",
): string {
  if (value === null || value === undefined || value.trim() === "") {
    return unavailableText(reason);
  }
  return value;
}

export function percentText(
  value: string | null | undefined,
  reason = "后端未返回该字段",
): string {
  if (value === null || value === undefined || value.trim() === "") {
    return unavailableText(reason);
  }
  return `${value}%`;
}

export function notionalText(
  value: string | null | undefined,
  currency: string | null | undefined,
  reason = "后端未返回名义价值",
): string {
  if (value === null || value === undefined || value.trim() === "") {
    return unavailableText(reason);
  }
  if (currency === null || currency === undefined || currency.trim() === "") {
    return `${value}（后端未返回币种）`;
  }
  return `${value} ${currency}`;
}

export function measureText(
  value: string | null | undefined,
  unit: string,
  reason = "后端未返回该字段",
): string {
  if (value === null || value === undefined || value.trim() === "") {
    return unavailableText(reason);
  }
  return `${value} ${unit}`;
}

export function riskLevelView(value: string | null | undefined): RiskLevelView {
  if (value === "low" || value === "medium" || value === "high") {
    return RISK_LEVEL_VIEWS[value];
  }
  return {
    label: unavailableText("后端未返回有效风险等级"),
    tone: UNAVAILABLE_TONE,
    available: false,
  };
}

export function ruleLevelView(value: string | null | undefined): RiskLevelView {
  if (value === "warning") {
    return {
      label: "预警",
      tone: "border-amber-600/40 text-amber-700 dark:text-amber-400",
      available: true,
    };
  }
  if (value === "critical") {
    return {
      label: "严重",
      tone: "border-rose-600/40 text-rose-700 dark:text-rose-400",
      available: true,
    };
  }
  return {
    label: unavailableText("后端未返回规则级别"),
    tone: UNAVAILABLE_TONE,
    available: false,
  };
}

export function riskRuleMeta(ruleId: string): RiskRuleMeta | null {
  return Object.prototype.hasOwnProperty.call(RISK_RULE_META, ruleId)
    ? RISK_RULE_META[ruleId]
    : null;
}

export function riskStatusLabel(status: string | null | undefined): string {
  if (status === "ok") return "正常";
  if (status === "empty") return "暂无持仓";
  return unavailableText("后端返回了未知状态");
}

export function marginUsageBasisLabel(basis: string | null | undefined): string {
  if (basis === "margin_ratio") return "账户保证金比率";
  if (basis === "used_margin") return "已用保证金 /（已用 + 可用）";
  return "未提供";
}

export function positionSourceLabel(source: string | null | undefined): string {
  if (source === "exchange") return "OKX 快照";
  if (source === "manual") return "手动持仓";
  if (source === null || source === undefined || source.trim() === "") {
    return unavailableText("后端未返回持仓来源");
  }
  return unavailableText("后端返回了未知持仓来源");
}

export function sectorLabel(sector: string | null | undefined): string {
  if (sector === null || sector === undefined || sector.trim() === "") {
    return unavailableText("后端未返回行业名称");
  }
  return sector === "unclassified" ? "未分类" : sector;
}

export function riskSideLabel(side: string | null | undefined): string {
  if (side === "long") return "多";
  if (side === "short") return "空";
  return unavailableText("后端未返回方向");
}

/** 顶层结构缺失时整块显示不可用；单个字段为空由各展示函数处理。 */
export function riskExposureProblem(value: unknown): string | null {
  if (typeof value !== "object" || value === null) {
    return "后端未返回风险与敞口数据";
  }
  const record = value as Record<string, unknown>;
  if (typeof record.as_of !== "string" || record.as_of.trim() === "") {
    return "后端返回缺少 as_of";
  }
  if (record.status !== "ok" && record.status !== "empty") {
    return "后端返回的 status 不是 ok 或 empty";
  }
  if (typeof record.summary !== "object" || record.summary === null) {
    return "后端返回缺少 summary";
  }
  if (!Array.isArray(record.positions)) return "后端返回缺少 positions";
  if (!Array.isArray(record.sectors)) return "后端返回缺少 sectors";
  if (!Array.isArray(record.rules)) return "后端返回缺少 rules";
  return null;
}
