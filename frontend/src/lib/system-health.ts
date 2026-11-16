/**
 * 设置页系统健康与密钥状态的展示文案。
 *
 * 五项状态、最后成功时间与错误摘要全部来自 `GET /api/system/health`，
 * 密钥状态来自 `GET /api/settings` 的 `secrets`。这里只做名称映射和排序，
 * 不推断状态，也不在时间缺失时用当前时间补造。
 */

import type { SecretSettings, SystemComponent, SystemHealthResponse } from "./api";
import { formatBeijingTime } from "./display";

export type HealthStatus = SystemComponent["status"];

/** 契约里的组件名是固定英文标识，界面用可读名称展示；未知名称原样显示。 */
const HEALTH_COMPONENT_LABELS: Record<string, string> = {
  database: "数据库",
  okx_rest: "OKX REST",
  okx_ws: "OKX WebSocket",
  job_queue: "任务队列",
  candle_coverage: "K 线覆盖",
};

export function healthComponentLabel(name: string): string {
  return HEALTH_COMPONENT_LABELS[name] ?? name;
}

export type HealthStatusView = {
  label: string;
  tone: string;
  healthy: boolean;
};

const HEALTH_STATUS_VIEWS: Record<HealthStatus, HealthStatusView> = {
  ok: {
    label: "正常",
    tone: "border-emerald-600/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
    healthy: true,
  },
  stale: {
    label: "陈旧",
    tone: "border-amber-600/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
    healthy: false,
  },
  error: {
    label: "异常",
    tone: "border-rose-600/40 bg-rose-500/10 text-rose-700 dark:text-rose-400",
    healthy: false,
  },
  unconfigured: {
    label: "未配置",
    tone: "border-border bg-muted/40 text-muted-foreground",
    healthy: false,
  },
};

export function healthStatusView(status: HealthStatus): HealthStatusView {
  return HEALTH_STATUS_VIEWS[status];
}

const SORT_RANK: Record<HealthStatus, number> = {
  error: 0,
  stale: 1,
  unconfigured: 2,
  ok: 3,
};

/** 异常项排在前面；同一状态内保持接口返回顺序，结果稳定可断言。 */
export function sortHealthComponents(
  components: readonly SystemComponent[],
): SystemComponent[] {
  return components
    .map((component, index) => ({ component, index }))
    .sort(
      (left, right) =>
        SORT_RANK[left.component.status] - SORT_RANK[right.component.status] ||
        left.index - right.index,
    )
    .map((item) => item.component);
}

/** 最后成功时间由后端给出；没有记录时写明「暂无成功记录」，不补造时间。 */
export function lastSuccessText(lastSuccessAt: string | null | undefined): string {
  if (lastSuccessAt === null || lastSuccessAt === undefined || lastSuccessAt.trim() === "") {
    return "暂无成功记录";
  }
  return formatBeijingTime(lastSuccessAt);
}

export function healthCheckedText(health: SystemHealthResponse): string {
  return formatBeijingTime(health.checked_at);
}

/** 整体状态直接取后端字段：`ok` 全部正常，`degraded` 表示有项异常。 */
export function overallHealthLabel(status: SystemHealthResponse["status"]): string {
  return status === "ok" ? "全部正常" : "部分异常";
}

/** 掩码后的 API Key；接口只给全掩码，页面不回显明文。 */
export function apiKeyMaskedText(secrets: SecretSettings): string {
  if (!secrets.okx_configured) return "未配置";
  return secrets.okx_api_key_masked ?? "已配置（接口未返回掩码）";
}

export function permissionLabel(permission: SecretSettings["okx_permission"]): string {
  if (permission === "read_only") return "只读";
  if (permission === "unknown") return "未知";
  return "未配置";
}

const HEALTH_STATUSES: readonly HealthStatus[] = ["ok", "stale", "error", "unconfigured"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readHealthStatus(value: unknown, where: string): HealthStatus {
  if (typeof value !== "string" || !HEALTH_STATUSES.includes(value as HealthStatus)) {
    throw new Error(`${where}的 status 不是契约里的状态`);
  }
  return value as HealthStatus;
}

function optionalText(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

/**
 * 校验并读取 `GET /api/system/health` 的响应。
 *
 * 上游返回 200 但内容不符合契约时（例如网关改写响应），直接抛错让页面显示可读的
 * 读取失败提示；不把缺失字段当成空列表或正常状态，否则会白屏或伪造健康。
 */
export function parseSystemHealth(value: unknown): SystemHealthResponse {
  if (!isRecord(value)) throw new Error("系统健康响应不是对象");
  if (value.status !== "ok" && value.status !== "degraded") {
    throw new Error("系统健康响应缺少整体 status");
  }
  if (typeof value.checked_at !== "string" || value.checked_at.trim() === "") {
    throw new Error("系统健康响应缺少 checked_at");
  }
  if (!Array.isArray(value.components)) {
    throw new Error("系统健康响应缺少 components");
  }
  const components = value.components.map((item, index) => {
    const where = `系统健康响应第 ${index + 1} 项`;
    if (!isRecord(item)) throw new Error(`${where}不是对象`);
    if (typeof item.name !== "string" || item.name.trim() === "") {
      throw new Error(`${where}缺少 name`);
    }
    const status = readHealthStatus(item.status, where);
    if (!Object.hasOwn(item, "last_success_at")) {
      throw new Error(`${where}缺少 last_success_at`);
    }
    const lastSuccessAt = item.last_success_at;
    if (lastSuccessAt !== null && typeof lastSuccessAt !== "string") {
      throw new Error(`${where}的 last_success_at 不是时间字符串或 null`);
    }
    return {
      name: item.name,
      status,
      last_success_at: lastSuccessAt,
      error: optionalText(item.error),
      detail: optionalText(item.detail),
    };
  });
  return { status: value.status, checked_at: value.checked_at, components };
}
