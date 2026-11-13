import { describe, expect, it } from "vitest";

import {
  actionLabel,
  buildCreatePayload,
  buildTradePayload,
  buildUpdatePayload,
  localDateTimeToIso,
  localDateTimeValue,
  newIdempotencyKey,
  NO_QUOTE_TEXT,
  positionStatusLabel,
  priceSourceLabel,
  quotePnlText,
  quoteSourceText,
  quoteText,
  sideLabel,
  tradePnlText,
  type ManualPosition,
} from "./manual-positions";

function position(overrides: Partial<ManualPosition> = {}): ManualPosition {
  return {
    asset_class: "tokenized_equity",
    avg_cost: "226.80",
    created_at: "2026-11-13T09:00:00Z",
    display_symbol: "AAPL-USDT",
    id: "0f6f6f0e-5b6f-4f0c-9b7a-7e5f8a1d2c34",
    inst_id: "AAPL-USDT-SWAP",
    name: "AAPL",
    price: "231.42",
    price_source: "okx_swap",
    price_status: "ok",
    quantity: "8",
    side: "long",
    status: "open",
    unrealized_pnl: "36.96",
    market_value: "1851.36",
    updated_at: "2026-11-13T09:00:00Z",
    ...overrides,
  };
}

describe("手动持仓展示文案", () => {
  it("方向、状态与流水动作使用可读文字", () => {
    expect(sideLabel("long")).toBe("多");
    expect(sideLabel("short")).toBe("空");
    expect(positionStatusLabel("open")).toBe("持仓中");
    expect(positionStatusLabel("closed")).toBe("已平仓");
    expect(actionLabel("open")).toBe("开仓");
    expect(actionLabel("add")).toBe("加仓");
    expect(actionLabel("reduce")).toBe("减仓");
    expect(actionLabel("close")).toBe("清仓");
    expect(actionLabel("correct")).toBe("更正");
  });

  it("价格来源按数据源区分，缺失写未提供", () => {
    expect(priceSourceLabel("okx")).toBe("OKX");
    expect(priceSourceLabel("okx_spot")).toBe("OKX 现货");
    expect(priceSourceLabel("okx_swap")).toBe("OKX 永续");
    expect(priceSourceLabel("us_equity_proxy")).toBe("美股代理行情");
    expect(priceSourceLabel(null)).toBe("未提供");
  });

  it("没有行情时价格、市值、来源与盈亏都写无行情源", () => {
    const item = position({
      price: null,
      market_value: null,
      price_source: null,
      price_status: "unavailable",
      unrealized_pnl: null,
    });

    expect(quoteText(item, item.price)).toBe(NO_QUOTE_TEXT);
    expect(quoteText(item, item.market_value)).toBe(NO_QUOTE_TEXT);
    expect(quotePnlText(item, item.unrealized_pnl)).toBe(NO_QUOTE_TEXT);
    expect(quoteSourceText(item)).toBe(NO_QUOTE_TEXT);
  });

  it("有行情时原样展示字符串，盈亏只补正负号", () => {
    const item = position();

    expect(quoteText(item, item.price)).toBe("231.42");
    expect(quoteText(item, item.market_value)).toBe("1851.36");
    expect(quotePnlText(item, item.unrealized_pnl)).toBe("+36.96");
    expect(quotePnlText(item, "-12.5")).toBe("-12.5");
    expect(quoteSourceText(item)).toBe("OKX 永续");
    expect(tradePnlText("39.50")).toBe("+39.50");
    expect(tradePnlText(null)).toBe("未提供");
  });
});

describe("手动持仓请求构造", () => {
  it("创建请求去掉首尾空白，空的可选字段提交 null", () => {
    expect(
      buildCreatePayload(
        {
          instId: " AAPL-USDT-SWAP ",
          side: "long",
          quantity: " 8 ",
          avgCost: "226.80",
          stopPx: "",
          leverage: "3",
          note: " 手动记账 ",
        },
        "key-1",
      ),
    ).toEqual({
      inst_id: "AAPL-USDT-SWAP",
      side: "long",
      quantity: "8",
      avg_cost: "226.80",
      stop_px: null,
      leverage: "3",
      note: "手动记账",
      idempotency_key: "key-1",
    });
  });

  it("编辑请求只包含止损价、杠杆和备注，空输入提交 null", () => {
    expect(
      buildUpdatePayload({ stopPx: "", leverage: "3", note: "" }),
    ).toEqual({ stop_px: null, leverage: "3", note: null });
  });

  it("交易请求把本地时间转成带时区的 UTC，更正流水手续费固定为 0", () => {
    const local = "2026-11-14T09:05";
    const payload = buildTradePayload(
      {
        action: "correct",
        quantity: "6",
        price: "220.00",
        fee: "9.99",
        occurredAt: local,
        note: " 更正成本 ",
      },
      "key-2",
    );

    expect(payload).toEqual({
      action: "correct",
      quantity: "6",
      price: "220.00",
      fee: "0",
      occurred_at: new Date(local).toISOString(),
      note: "更正成本",
      idempotency_key: "key-2",
    });
  });

  it("datetime-local 的文本与时间可以互相还原", () => {
    const moment = new Date(2026, 10, 14, 9, 5);
    expect(localDateTimeToIso(localDateTimeValue(moment))).toBe(moment.toISOString());
    expect(localDateTimeToIso("not-a-time")).toBe("not-a-time");
  });

  it("每次生成的幂等键都不相同", () => {
    const first = newIdempotencyKey();
    const second = newIdempotencyKey();
    expect(first).not.toBe("");
    expect(second).not.toBe(first);
  });
});
