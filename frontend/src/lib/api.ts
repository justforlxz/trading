/**
 * 后端 HTTP 客户端。
 *
 * v2 骨架只暴露健康检查；业务端点随对应节点在这里逐个加入，
 * 不预先声明尚未实现的类型。
 */

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
