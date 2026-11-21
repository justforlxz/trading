import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import type { SettingsResponse, SystemHealthResponse } from "../../lib/api";
import { toSettingsDraft } from "../../lib/settings-draft";
import { SettingsView, type SettingsViewProps } from "../settings";

const SETTINGS: SettingsResponse = {
  display: {
    color_scheme: "system",
    default_bar: "1d",
    price_precision: 2,
    home_layout: "cockpit",
  },
  risk_defaults: {
    default_leverage: "3",
    risk_budget_per_trade: "100",
    warning_threshold: "80",
    stop_rule: "fixed_pct",
  },
  execution: { auto_trading_enabled: false },
  data_sources: {
    subscribed_instruments: ["BTC-USDT", "ETH-USDT-SWAP"],
    last_sync_at: "2026-11-15T06:00:00Z",
    failure_count: 2,
  },
  notifications: { channels: ["browser"] },
  secrets: {
    okx_api_key_masked: "********",
    okx_configured: true,
    okx_permission: "read_only",
  },
  updated_at: "2026-11-15T06:10:00Z",
};

const HEALTH: SystemHealthResponse = {
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
      name: "okx_rest",
      status: "ok",
      last_success_at: "2026-11-15T05:00:00Z",
      error: null,
      detail: "最近一次 K 线同步成功",
    },
    {
      name: "okx_ws",
      status: "unconfigured",
      last_success_at: null,
      error: null,
      detail: "推送层未启动",
    },
    {
      name: "job_queue",
      status: "ok",
      last_success_at: "2026-11-15T06:00:00Z",
      error: null,
      detail: null,
    },
    {
      name: "candle_coverage",
      status: "stale",
      last_success_at: "2026-11-15T05:00:00Z",
      error: "最近一次同步距今超过阈值",
      detail: "三个周期覆盖完整",
    },
  ],
};

function props(overrides: Partial<SettingsViewProps> = {}): SettingsViewProps {
  return {
    settings: SETTINGS,
    draft: toSettingsDraft(SETTINGS),
    instrumentsText: "BTC-USDT, ETH-USDT-SWAP",
    apiKey: "",
    health: HEALTH,
    healthLoading: false,
    healthError: null,
    busy: false,
    error: null,
    notice: null,
    notificationPermission: "default",
    onDraftChange: () => undefined,
    onInstrumentsTextChange: () => undefined,
    onApiKeyChange: () => undefined,
    onColorSchemeChange: () => undefined,
    onSave: () => undefined,
    onRefreshHealth: () => undefined,
    onRequestNotificationPermission: () => undefined,
    ...overrides,
  };
}

function render(overrides: Partial<SettingsViewProps> = {}): string {
  return renderToStaticMarkup(createElement(SettingsView, props(overrides)));
}

describe("设置页", () => {
  it("只展示 v6 的四类设置与规格保留的自动执行开关", () => {
    const html = render();
    for (const title of ["数据连接", "显示偏好", "风险默认值", "自动执行", "密钥状态"]) {
      expect(html).toContain(title);
    }
    expect(html).not.toContain("执行模式");
    expect(html).not.toContain("紧急停止");
    expect(html).not.toContain("代理分组");
    expect(html).not.toContain("costs");
    expect(html).not.toContain("backtest");
  });

  it("系统健康逐项展示五项状态、最后成功时间与错误摘要", () => {
    const html = render();
    expect(html).toContain("整体状态：部分异常");
    expect(html).toContain("检查时间：2026-11-15 14:10（北京时间）");
    for (const label of ["数据库", "OKX REST", "OKX WebSocket", "任务队列", "K 线覆盖"]) {
      expect(html).toContain(label);
    }
    expect(html).not.toContain("外部 Provider");
    expect(html).toContain("最后成功时间：2026-11-15 14:00");
    expect(html).toContain("最后成功时间：暂无成功记录");
    expect(html).toContain("详情：最近一次 K 线同步成功");
    expect(html).toContain("陈旧");
    expect(html).toContain("未配置");
  });

  it("健康异常的项排在正常项前面", () => {
    const html = render();
    expect(html.indexOf("OKX WebSocket")).toBeLessThan(html.indexOf("数据库"));
  });

  it("数据连接不含 Provider 输入，只保留订阅标的与 OKX 同步状态", () => {
    const html = render();
    expect(html).not.toContain("Provider");
    expect(html).toContain("订阅标的（逗号分隔）");
    expect(html).toContain("最后同步：");
    expect(html).toContain("失败次数：2");
  });

  it("密钥区只显示掩码和配置状态，不出现 Secret 与 Passphrase 的值", () => {
    const html = render();
    expect(html).toContain("API Key（掩码）");
    expect(html).toContain("********");
    expect(html).toContain("已配置");
    expect(html).toContain("只读");
    expect(html).toContain("由环境变量注入，接口不返回是否设置");
    expect(html).not.toContain("okx_secret_key");
    expect(html).not.toContain("okx_passphrase");
  });

  it("健康接口不可用时显示错误，不伪装成正常", () => {
    const html = render({
      health: null,
      healthLoading: false,
      healthError: "系统健康读取失败（HTTP 503）",
    });
    expect(html).toContain("系统健康读取失败（HTTP 503）");
    expect(html).not.toContain("最后成功时间");
    expect(html).not.toContain("整体状态");
  });

  it("健康响应不符合契约时只降级健康区，其余设置继续可用", () => {
    const html = render({
      health: null,
      healthLoading: false,
      healthError: "系统健康响应缺少 components",
    });
    expect(html).toContain("系统健康响应缺少 components");
    for (const title of ["数据连接", "显示偏好", "风险默认值", "自动执行", "密钥状态"]) {
      expect(html).toContain(title);
    }
    expect(html).toContain("API Key（掩码）");
  });

  it("健康接口读取中不展示编造的状态与时间", () => {
    const html = render({ health: null, healthLoading: true, healthError: null });
    expect(html).toContain("正在读取系统健康…");
    expect(html).not.toContain("全部正常");
    expect(html).not.toContain("最后成功时间");
  });
});
