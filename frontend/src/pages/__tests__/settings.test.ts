import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import type { DeliveryItem, SettingsResponse, SystemHealthResponse } from "../../lib/api";
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
    macro: {
      series: {
        us10y: { minute: "yahoo", daily: "treasury" },
        us2y: { minute: null, daily: "treasury" },
        vix: { minute: "yahoo", daily: "cboe" },
      },
      scheduler: { minute: "1m" },
    },
    equity: {
      provider: "yahoo",
      symbols: ["SPY", "QQQ"],
      scheduler: { minute: "1m" },
    },
  },
  notifications: {
    channels: ["browser", "telegram"],
    telegram: { chat_id: "-1001234567890", token_configured: true },
    webhook: { url: "https://example.invalid/hooks/trading", secret_configured: false },
  },
  secrets: {
    okx_api_key_masked: "********",
    okx_configured: true,
    okx_permission: "read_only",
  },
  updated_at: "2026-11-15T06:10:00Z",
};

const DELIVERIES: DeliveryItem[] = [
  {
    id: "nd_3f9c1a7b5e2d4c6f8a0b1c2d",
    channel: "telegram",
    alert_id: "al_XAAPL-USDT_20261120120000000000",
    status: "delivered",
    error: null,
    created_at: "2026-11-20T12:00:03Z",
  },
  {
    id: "nd_7a1c3e5b9d2f4a6c8e0b1d3f",
    channel: "webhook",
    alert_id: null,
    status: "failed",
    error: "HTTP 404（永久错误，不重试）",
    created_at: "2026-11-20T12:01:03Z",
  },
];

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
    deliveries: DELIVERIES,
    deliveriesLoading: false,
    deliveriesError: null,
    testingChannel: null,
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
    onRefreshDeliveries: () => undefined,
    onTestChannel: () => undefined,
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
    for (const title of ["数据连接", "显示偏好", "风险默认值", "自动执行", "通知", "密钥状态"]) {
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

  it("数据连接只暴露可切换的数据源，不暴露上游地址与任意 provider 名", () => {
    const html = render();
    expect(html).not.toContain("Provider");
    expect(html).toContain("订阅标的（逗号分隔）");
    expect(html).toContain("最后同步：");
    expect(html).toContain("失败次数：2");
    // 美股数据源是下拉选择：可选值来自实现，界面不能自由输入。
    expect(html).toContain("美股数据源");
    expect(html).toContain("Yahoo（分钟级，延迟 15 分钟）");
    expect(html).toContain("Stooq（日线，延迟，备用）");
    expect(html).toContain("美股标的（逗号分隔）");
    expect(html).toContain("SPY, QQQ");
    // 上游地址是服务端配置，页面不出现。
    expect(html).not.toContain("query1.finance.yahoo.com");
    expect(html).not.toContain("stooq.com");
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

  it("三个通道各自一个开关，接收方与凭据状态分开展示", () => {
    const html = render();
    for (const label of ["浏览器 通道", "Telegram 通道", "Webhook 通道"]) {
      expect(html).toContain(label);
    }
    expect(html).toContain("chat_id");
    expect(html).toContain("-1001234567890");
    expect(html).toContain("https://example.invalid/hooks/trading");
    // token 已配置、签名密钥未配置：页面只说这两种说法，不给输入框。
    expect(html).toContain("已配置（环境变量 TELEGRAM_BOT_TOKEN）");
    expect(html).toContain("未配置（环境变量 WEBHOOK_SIGNING_SECRET，未配置就不加签）");
    expect(html).not.toContain("bot-token");
    expect(html).not.toContain("signing-secret");
  });

  it("勾选的通道与接口返回的清单一致", () => {
    const html = render();
    // 响应里开着 browser 与 telegram：两个复选框勾上，webhook 不勾。
    expect((html.match(/checked=""/g) ?? []).length).toBe(2);
    expect(html).toContain("Webhook 通道");
  });

  it("每个通道一组类型复选框与最低严重度下拉", () => {
    const html = render({
      draft: {
        ...toSettingsDraft(SETTINGS),
        notifications: {
          ...toSettingsDraft(SETTINGS).notifications,
          subscriptions: {
            browser: { types: ["risk", "indicator"], minSeverity: "info" },
            telegram: { types: ["risk"], minSeverity: "warning" },
            webhook: { types: [], minSeverity: "critical" },
          },
        },
      },
    });
    for (const label of ["持仓风险", "策略信号", "技术形态", "价格区间", "数据缺口"]) {
      expect(html).toContain(label);
    }
    expect(html).toContain("最低严重度");
    // 三个通道各一个下拉：值来自草稿，未配置时是「提示」。
    expect(html).toContain('<option value="info" selected="">提示</option>');
    expect(html).toContain('<option value="warning" selected="">警告</option>');
    expect(html).toContain('<option value="critical" selected="">紧急</option>');
    // 勾选状态来自草稿：browser 两个、telegram 一个，webhook 没有。
    expect((html.match(/checked=""/g) ?? []).length).toBe(2 + 3 + 0);
  });

  it("最近投递逐条展示时间、通道、状态与失败原因", () => {
    const html = render();
    expect(html).toContain("最近投递");
    expect(html).toContain("2026-11-20 20:00（北京时间）");
    expect(html).toContain("Telegram · 成功");
    expect(html).toContain("Webhook · 失败");
    expect(html).toContain("错误：HTTP 404（永久错误，不重试）");
  });

  it("没有投递记录时如实显示空状态", () => {
    const html = render({ deliveries: [] });
    expect(html).toContain("还没有投递记录。");
  });

  it("投递读取中与读取失败都不伪造记录", () => {
    expect(render({ deliveries: [], deliveriesLoading: true })).toContain("正在读取最近投递…");
    const failed = render({ deliveries: [], deliveriesError: "最近投递读取失败（HTTP 500）" });
    expect(failed).toContain("最近投递读取失败（HTTP 500）");
    expect(failed).toContain("还没有投递记录。");
  });

  it("测试发送进行中时按钮显示发送中", () => {
    expect(render({ testingChannel: "telegram" })).toContain("发送中…");
  });

  it("填了 chat_id 但没保存时，提示测试发送只用已保存值", () => {
    const draft = toSettingsDraft(SETTINGS);
    const html = render({
      draft: {
        ...draft,
        notifications: {
          ...draft.notifications,
          telegramChatId: "11111111",
          webhookUrl: "https://draft.invalid/hooks/trading",
        },
      },
    });
    // 输入框里已经有值，就不能再要求「先在上面填写」——测试发送根本读不到草稿值。
    expect(html).toContain("测试发送只用已保存的 chat_id");
    expect(html).toContain("测试发送只用已保存的接收地址");
    expect(html).not.toContain("先在上面填写");
  });

  it("还没有保存过接收方（首次配置）时提示先保存再测试", () => {
    const html = render({
      settings: {
        ...SETTINGS,
        notifications: {
          channels: SETTINGS.notifications.channels,
          telegram: { chat_id: "", token_configured: true },
          webhook: { url: "", secret_configured: false },
        },
      },
      draft: toSettingsDraft({
        ...SETTINGS,
        notifications: {
          channels: SETTINGS.notifications.channels,
          telegram: { chat_id: "", token_configured: true },
          webhook: { url: "", secret_configured: false },
        },
      }),
    });
    expect(html).toContain("测试发送只用已保存的 chat_id");
    expect(html).toContain("测试发送只用已保存的接收地址");
    expect(html).toContain("chat_id 由给 bot 发过消息后取得");
  });

  it("草稿与已保存值一致时不显示测试发送的提示", () => {
    const html = render();
    expect(html).not.toContain("测试发送只用已保存的");
  });
});
