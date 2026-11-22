import { describe, expect, it } from "vitest";

import type { NotificationSettings } from "./api";
import {
  channelLabel,
  credentialText,
  instrumentsToText,
  notificationsPatch,
  parseInstruments,
  toNotificationDraft,
  withChannel,
} from "./settings-draft";

const NOTIFICATIONS: NotificationSettings = {
  channels: ["browser", "telegram"],
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
  it("接口的嵌套分组拍平成三条输入，缺项按未配置处理", () => {
    expect(toNotificationDraft(NOTIFICATIONS)).toEqual({
      channels: ["browser", "telegram"],
      telegramChatId: "-1001234567890",
      webhookUrl: "https://example.invalid/hooks/trading",
    });
    expect(toNotificationDraft({})).toEqual({
      channels: [],
      telegramChatId: "",
      webhookUrl: "",
    });
  });

  it("切换一个通道不丢失其它通道的开关", () => {
    const opened = withChannel(["browser", "telegram"], "webhook", true);
    expect(opened).toEqual(["browser", "telegram", "webhook"]);
    expect(withChannel(opened, "browser", false)).toEqual(["telegram", "webhook"]);
    expect(withChannel(["browser"], "telegram", false)).toEqual(["browser"]);
  });

  it("保存载荷带全三个子项，接收方去空白", () => {
    expect(
      notificationsPatch({
        channels: ["telegram"],
        telegramChatId: "  -100999  ",
        webhookUrl: "",
      }),
    ).toEqual({
      channels: ["telegram"],
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
