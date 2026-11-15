import { describe, expect, it } from "vitest";

import type { SystemComponent } from "./api";
import {
  apiKeyMaskedText,
  healthCheckedText,
  healthComponentLabel,
  healthStatusView,
  lastSuccessText,
  overallHealthLabel,
  parseSystemHealth,
  permissionLabel,
  sortHealthComponents,
} from "./system-health";

function component(
  name: string,
  status: SystemComponent["status"],
  lastSuccessAt: string | null = null,
): SystemComponent {
  return { name, status, last_success_at: lastSuccessAt, error: null, detail: null };
}

describe("系统健康展示", () => {
  it("六个固定组件名显示可读名称，未知名称原样保留", () => {
    expect(healthComponentLabel("database")).toBe("数据库");
    expect(healthComponentLabel("okx_rest")).toBe("OKX REST");
    expect(healthComponentLabel("okx_ws")).toBe("OKX WebSocket");
    expect(healthComponentLabel("external_provider")).toBe("外部 Provider");
    expect(healthComponentLabel("job_queue")).toBe("任务队列");
    expect(healthComponentLabel("candle_coverage")).toBe("K 线覆盖");
    expect(healthComponentLabel("backup")).toBe("backup");
  });

  it("状态文案直接对应接口枚举，不新增推断出的等级", () => {
    expect(healthStatusView("ok")).toMatchObject({ label: "正常", healthy: true });
    expect(healthStatusView("stale")).toMatchObject({ label: "陈旧", healthy: false });
    expect(healthStatusView("error")).toMatchObject({ label: "异常", healthy: false });
    expect(healthStatusView("unconfigured")).toMatchObject({ label: "未配置", healthy: false });
    expect(overallHealthLabel("ok")).toBe("全部正常");
    expect(overallHealthLabel("degraded")).toBe("部分异常");
  });

  it("异常项排在正常项前面，同状态保持接口顺序", () => {
    const sorted = sortHealthComponents([
      component("database", "ok"),
      component("candle_coverage", "stale"),
      component("job_queue", "ok"),
      component("external_provider", "error"),
      component("okx_ws", "unconfigured"),
      component("okx_rest", "ok"),
    ]);
    expect(sorted.map((item) => item.name)).toEqual([
      "external_provider",
      "candle_coverage",
      "okx_ws",
      "database",
      "job_queue",
      "okx_rest",
    ]);
  });

  it("最后成功时间缺失时写明暂无记录，不做补造", () => {
    expect(lastSuccessText(null)).toBe("暂无成功记录");
    expect(lastSuccessText("")).toBe("暂无成功记录");
    expect(lastSuccessText("2026-11-15T06:10:00Z")).toBe("2026-11-15 14:10");
  });

  it("检查时间按北京时间显示，非法输入原样返回", () => {
    expect(healthCheckedText({ status: "ok", checked_at: "2026-11-15T06:10:00Z", components: [] })).toBe(
      "2026-11-15 14:10",
    );
    expect(healthCheckedText({ status: "ok", checked_at: "not-a-time", components: [] })).toBe(
      "not-a-time",
    );
  });

  it("密钥状态只使用接口返回的掩码和配置标记", () => {
    expect(
      apiKeyMaskedText({ okx_configured: false, okx_api_key_masked: null, okx_permission: null }),
    ).toBe("未配置");
    expect(
      apiKeyMaskedText({
        okx_configured: true,
        okx_api_key_masked: "********",
        okx_permission: "read_only",
      }),
    ).toBe("********");
    expect(permissionLabel("read_only")).toBe("只读");
    expect(permissionLabel("unknown")).toBe("未知");
    expect(permissionLabel(null)).toBe("未配置");
  });
});

describe("系统健康响应校验", () => {
  const valid = {
    status: "degraded",
    checked_at: "2026-11-15T06:10:00Z",
    components: [
      {
        name: "database",
        status: "ok",
        last_success_at: "2026-11-15T06:10:00Z",
        error: null,
        detail: null,
      },
      {
        name: "okx_ws",
        status: "unconfigured",
        last_success_at: null,
        error: "连接未启动",
        detail: "okx / public_ws",
        future_field: "ignored",
      },
    ],
  };

  it("符合契约的响应读取为页面使用的形状，附加字段被忽略", () => {
    expect(parseSystemHealth(valid)).toEqual({
      status: "degraded",
      checked_at: "2026-11-15T06:10:00Z",
      components: [
        {
          name: "database",
          status: "ok",
          last_success_at: "2026-11-15T06:10:00Z",
          error: null,
          detail: null,
        },
        {
          name: "okx_ws",
          status: "unconfigured",
          last_success_at: null,
          error: "连接未启动",
          detail: "okx / public_ws",
        },
      ],
    });
  });

  it("缺少 components 时抛错，不把它当成空列表", () => {
    expect(() => parseSystemHealth({ status: "ok", checked_at: "2026-11-15T06:10:00Z" })).toThrow(
      "缺少 components",
    );
    expect(() =>
      parseSystemHealth({ status: "ok", checked_at: "2026-11-15T06:10:00Z", components: {} }),
    ).toThrow("缺少 components");
  });

  it("整体状态或检查时间不合法时抛错", () => {
    expect(() => parseSystemHealth({ ...valid, status: "healthy" })).toThrow("整体 status");
    expect(() => parseSystemHealth({ ...valid, checked_at: "" })).toThrow("checked_at");
    expect(() => parseSystemHealth(null)).toThrow("不是对象");
  });

  it("组件缺少 name、status 或 last_success_at 时抛错", () => {
    expect(() =>
      parseSystemHealth({
        ...valid,
        components: [{ status: "ok", last_success_at: null, error: null, detail: null }],
      }),
    ).toThrow("缺少 name");
    expect(() =>
      parseSystemHealth({
        ...valid,
        components: [{ name: "database", status: "unknown", last_success_at: null }],
      }),
    ).toThrow("status 不是契约里的状态");
    expect(() =>
      parseSystemHealth({ ...valid, components: [{ name: "database", status: "ok" }] }),
    ).toThrow("缺少 last_success_at");
  });
});
