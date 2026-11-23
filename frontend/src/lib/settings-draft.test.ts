import { describe, expect, it } from "vitest";

import type { NotificationSettings } from "./api";
import {
  EQUITY_PROVIDERS,
  channelLabel,
  credentialText,
  equityPatch,
  instrumentsToText,
  notificationsPatch,
  parseInstruments,
  toEquityDraft,
  toNotificationDraft,
  withChannel,
  withMinSeverity,
  withSubscriptionType,
} from "./settings-draft";

const NOTIFICATIONS: NotificationSettings = {
  channels: ["browser", "telegram"],
  subscriptions: {
    browser: { types: ["risk", "strategy"], min_severity: "warning" },
    telegram: { types: [], min_severity: "warning" },
    webhook: { types: [], min_severity: "info" },
  },
  telegram: { chat_id: "-1001234567890", token_configured: true },
  webhook: { url: "https://example.invalid/hooks/trading", secret_configured: false },
};

describe("订阅标的输入", () => {
  it("逐项键入过程中，每次中间文本都能解析回已完成的标的", () => {
    // 模拟用户逐字符键入 "BTC-USDT, ETH-USDT"：中间态的可解析结果必须单调增长，
    // 且解析不会回头改写输入原文，否则逗号会在下一次渲染前消失。
    const typed = "BTC-USDT, ETH-USDT";
    const steps = Array.from({ length: typed.length }, (_, index) => typed.slice(0, index + 1));
    const parsed = steps.map((text) => parseInstruments(text).length);
    // 只有某个前缀恰好构成 "BTC-USDT," 这类带尾随逗号的输入时，已完成的标的数量才会增加。
    expect(parsed[parsed.length - 1]).toBe(2);
    expect(parseInstruments("BTC-USDT,")).toEqual(["BTC-USDT"]);
    for (const step of steps) {
      expect(parseInstruments(step)).toEqual(
        step
          .split(",")
          .map((item) => item.trim())
          .filter((item) => item !== ""),
      );
    }
  });

  it("保存时按逗号拆分并去掉空白项", () => {
    expect(parseInstruments("BTC-USDT, ETH-USDT-SWAP,")).toEqual([
      "BTC-USDT",
      "ETH-USDT-SWAP",
    ]);
    expect(parseInstruments("  ,  ")).toEqual([]);
    expect(parseInstruments("")).toEqual([]);
  });

  it("接口数组还原成逗号分隔文本", () => {
    expect(instrumentsToText(["BTC-USDT", "AAPL-USDT-SWAP"])).toBe(
      "BTC-USDT, AAPL-USDT-SWAP",
    );
    expect(instrumentsToText([])).toBe("");
  });

  it("接口数组与输入文本可以往返，不丢标的也不改变顺序", () => {
    const instruments = ["BTC-USDT", "ETH-USDT-SWAP", "AAPL-USDT-SWAP"];
    expect(parseInstruments(instrumentsToText(instruments))).toEqual(instruments);
    expect(parseInstruments(instrumentsToText([]))).toEqual([]);
  });
});

describe("通知设置草稿", () => {
  it("接口的嵌套分组拍平成草稿，缺项按未配置处理", () => {
    expect(toNotificationDraft(NOTIFICATIONS)).toEqual({
      channels: ["browser", "telegram"],
      subscriptions: {
        browser: { types: ["risk", "strategy"], minSeverity: "warning" },
        telegram: { types: [], minSeverity: "warning" },
        webhook: { types: [], minSeverity: "info" },
      },
      telegramChatId: "-1001234567890",
      webhookUrl: "https://example.invalid/hooks/trading",
    });
    expect(toNotificationDraft({})).toEqual({
      channels: [],
      subscriptions: {
        browser: { types: [], minSeverity: "info" },
        telegram: { types: [], minSeverity: "info" },
        webhook: { types: [], minSeverity: "info" },
      },
      telegramChatId: "",
      webhookUrl: "",
    });
  });

  it("勾选与取消一个类型只改该通道，最低严重度单独可改", () => {
    const draft = toNotificationDraft(NOTIFICATIONS).subscriptions;
    const added = withSubscriptionType(draft, "telegram", "risk", true);
    expect(added.telegram.types).toEqual(["risk"]);
    expect(added.telegram.minSeverity).toBe("warning");
    expect(added.browser).toEqual(draft.browser);

    const removed = withSubscriptionType(added, "telegram", "risk", false);
    expect(removed.telegram.types).toEqual([]);

    const stricter = withMinSeverity(draft, "browser", "critical");
    expect(stricter.browser).toEqual({ types: ["risk", "strategy"], minSeverity: "critical" });
  });

  it("切换一个通道不丢失其它通道的开关", () => {
    const opened = withChannel(["browser", "telegram"], "webhook", true);
    expect(opened).toEqual(["browser", "telegram", "webhook"]);
    expect(withChannel(opened, "browser", false)).toEqual(["telegram", "webhook"]);
    expect(withChannel(["browser"], "telegram", false)).toEqual(["browser"]);
  });

  it("保存载荷带全四个子项，接收方去空白", () => {
    expect(
      notificationsPatch({
        channels: ["telegram"],
        subscriptions: {
          browser: { types: ["risk"], minSeverity: "warning" },
          telegram: { types: [], minSeverity: "critical" },
          webhook: { types: ["data"], minSeverity: "info" },
        },
        telegramChatId: "  -100999  ",
        webhookUrl: "",
      }),
    ).toEqual({
      channels: ["telegram"],
      subscriptions: {
        browser: { types: ["risk"], min_severity: "warning" },
        telegram: { types: [], min_severity: "critical" },
        webhook: { types: ["data"], min_severity: "info" },
      },
      telegram: { chat_id: "-100999" },
      webhook: { url: "" },
    });
  });

  it("通道标签与凭据状态只有固定说法", () => {
    expect(channelLabel("browser")).toBe("浏览器");
    expect(channelLabel("telegram")).toBe("Telegram");
    expect(channelLabel("webhook")).toBe("Webhook");
    expect(channelLabel("imessage")).toBe("imessage");
    expect(credentialText(true)).toBe("已配置");
    expect(credentialText(false)).toBe("未配置");
  });
});

describe("美股数据源", () => {
  it("接口返回的标的清单 → 逗号分隔的输入原文", () => {
    expect(toEquityDraft({ provider: "yahoo", symbols: ["SPY", "QQQ"], scheduler: { minute: "1m" } })).toEqual({
      provider: "yahoo",
      symbols: "SPY, QQQ",
    });
    expect(toEquityDraft(undefined)).toEqual({ provider: "", symbols: "" });
  });

  it("保存时把两个子项拆回接口字段", () => {
    expect(equityPatch({ provider: "stooq", symbols: "SPY, QQQ" })).toEqual({
      provider: "stooq",
      symbols: ["SPY", "QQQ"],
    });
    // 只改 provider 时不顺手覆盖标的清单。
    expect(equityPatch({ provider: "stooq", symbols: "  " })).toEqual({ provider: "stooq" });
    // 什么都不提交时返回 null：空 provider 与空清单都不该覆盖已保存的值。
    expect(equityPatch({ provider: "", symbols: "" })).toBeNull();
  });

  it("可选实现都是延迟行情，标签写明粒度", () => {
    expect(EQUITY_PROVIDERS.map((item) => item.value)).toEqual(["yahoo", "stooq"]);
    for (const option of EQUITY_PROVIDERS) {
      expect(option.label).toContain("延迟");
    }
  });
});
