import { describe, expect, it } from "vitest";

import { matchesCategory } from "../../lib/watchlist";
import {
  aggregateWatchlist,
  averageChangeText,
  buildPendingDigest,
  CHANGE_BUCKET_LABELS,
  changeBucket,
  PENDING_VISIBLE_LIMIT,
  signalText,
  signalTone,
  stripSwapSuffix,
  watchlistOwner,
} from "../../lib/watchlist-summary";
import { makeAlert, makeItem, makeSignal } from "./watchlist-fixtures";

describe("涨跌分桶口径", () => {
  it("大于 0 是上涨，小于 0 是下跌，等于 0 与取不到值都算平盘 / 无数据", () => {
    expect(changeBucket("1.86")).toBe("up");
    expect(changeBucket("0.0001")).toBe("up");
    expect(changeBucket("-0.44")).toBe("down");
    expect(changeBucket("0")).toBe("flat");
    expect(changeBucket("0.00")).toBe("flat");
    expect(changeBucket(null)).toBe("flat");
    expect(changeBucket("不是数字")).toBe("flat");
  });

  it("「平盘 / 无数据」必须完整写出，不能简写成「平盘」", () => {
    expect(CHANGE_BUCKET_LABELS.flat).toBe("平盘 / 无数据");
  });
});

describe("关注汇总（AC3）", () => {
  const three = [
    makeItem("A-USDT-SWAP", { change: "1" }),
    makeItem("B-USDT-SWAP", { change: "-1" }),
    makeItem("C-USDT-SWAP", { change: null }),
  ];

  it("上涨 1 / 下跌 1 / 平盘·无数据 1，平均 0.00%，有信号 0", () => {
    const aggregate = aggregateWatchlist(three);

    expect(aggregate.total).toBe(3);
    expect(aggregate.distribution).toEqual({ up: 1, down: 1, flat: 1 });
    expect(aggregate.signalCount).toBe(0);
    expect(averageChangeText(aggregate.averageChangePct)).toBe("0.00%");
  });

  it("平均涨跌只对有 change_pct_24h 的标的取算术平均", () => {
    const aggregate = aggregateWatchlist([
      makeItem("A-USDT-SWAP", { change: "2" }),
      makeItem("B-USDT-SWAP", { change: null }),
      makeItem("C-USDT-SWAP", { change: "4" }),
    ]);

    expect(aggregate.averageChangePct).toBe(3);
    expect(averageChangeText(aggregate.averageChangePct)).toBe("3.00%");
  });

  it("一个可算的涨跌都没有时写「—」，不把 null 当 0", () => {
    const aggregate = aggregateWatchlist([makeItem("A-USDT-SWAP", { change: null })]);

    expect(aggregate.averageChangePct).toBeNull();
    expect(averageChangeText(aggregate.averageChangePct)).toBe("—");
  });

  it("有信号只数 last_signal，不拿「是否有策略」代替", () => {
    const aggregate = aggregateWatchlist([
      makeItem("A-USDT-SWAP", {
        strategy: {
          enabled: true,
          execution_mode: "paper",
          instance_id: "si_0001",
          name: "AAPL 趋势",
          status: "live_running",
        },
      }),
      makeItem("B-USDT-SWAP", { signal: makeSignal("BUY", "MA20 上穿 MA60") }),
    ]);

    expect(aggregate.signalCount).toBe(1);
  });
});

describe("信号列文字与色条档位", () => {
  it("没有信号、HOLD 都写「无信号」，色条是灰色", () => {
    expect(signalText(makeItem("A", { signal: null }))).toBe("无信号");
    expect(signalTone(makeItem("A", { signal: null }))).toBe("none");
    expect(signalText(makeItem("A", { signal: makeSignal("HOLD", "横盘") }))).toBe("无信号");
    expect(signalTone(makeItem("A", { signal: makeSignal("HOLD", "横盘") }))).toBe("none");
  });

  it("BUY 是看多、SELL 是需注意，文字用信号自己的解释", () => {
    const buy = makeItem("A", { signal: makeSignal("BUY", "MA20 上穿 MA60") });
    const sell = makeItem("A", { signal: makeSignal("SELL", "跌破 MA20") });

    expect(signalText(buy)).toBe("MA20 上穿 MA60");
    expect(signalTone(buy)).toBe("bullish");
    expect(signalText(sell)).toBe("跌破 MA20");
    expect(signalTone(sell)).toBe("attention");
  });

  it("信号没有解释时退回动作本身的档位名", () => {
    expect(signalText(makeItem("A", { signal: makeSignal("BUY", "  ") }))).toBe("看多");
    expect(signalText(makeItem("A", { signal: makeSignal("SELL", "") }))).toBe("需注意");
  });
});

describe("需要处理（AC4）", () => {
  const tracked = [
    makeItem("BTC-USDT-SWAP"),
    makeItem("ETH-USDT-SWAP"),
    makeItem("SOL-USDT-SWAP"),
  ];
  // 提醒挂的是现货标识，自选里是永续标识，靠归属规则对上。
  const alerts = [
    makeAlert("al_1", "持仓缺少止损", "BTC-USDT"),
    makeAlert("al_2", "持仓缺少止损", "ETH-USDT"),
    makeAlert("al_3", "数据延迟", "SOL-USDT"),
  ];

  it("只有 3 条待处理提醒时显示 3 项，没有溢出", () => {
    const digest = buildPendingDigest(tracked, alerts);

    expect(digest.total).toBe(3);
    expect(digest.entries).toHaveLength(3);
    expect(digest.overflow).toBe(0);
    // 展示成自选里的 inst_id，和列表行对得上。
    expect(digest.entries.map((entry) => entry.label)).toEqual([
      "BTC-USDT-SWAP",
      "ETH-USDT-SWAP",
      "SOL-USDT-SWAP",
    ]);
  });

  it("再加 4 条信号时总数 7，只展示 6 条并出现「另有 1 项」", () => {
    const withSignals = [
      ...tracked,
      makeItem("S1-USDT-SWAP", { signal: makeSignal("BUY", "MA20 上穿 MA60") }),
      makeItem("S2-USDT-SWAP", { signal: makeSignal("SELL", "跌破 MA20") }),
      makeItem("S3-USDT-SWAP", { signal: makeSignal("BUY", "MACD 金叉") }),
      makeItem("S4-USDT-SWAP", { signal: makeSignal("BUY", "放量突破") }),
    ];

    const digest = buildPendingDigest(withSignals, alerts);

    expect(digest.total).toBe(7);
    expect(digest.entries).toHaveLength(PENDING_VISIBLE_LIMIT);
    expect(digest.overflow).toBe(1);
    // 信号排在提醒前面，和列表左栏的顺序一致。
    expect(digest.entries[0].key).toBe("signal:S1-USDT-SWAP");
    expect(digest.entries[5].key).toBe("alert:al_2");
  });

  it("没有信号也没有提醒时总数为 0，条目为空", () => {
    const digest = buildPendingDigest([makeItem("A-USDT-SWAP")], []);

    expect(digest.total).toBe(0);
    expect(digest.entries).toEqual([]);
    expect(digest.overflow).toBe(0);
  });
});

describe("提醒归属（AC10）", () => {
  it("去掉 -SWAP 后缀后相等才算归属：BTC-USDT 计入 BTC-USDT-SWAP", () => {
    const items = [makeItem("BTC-USDT-SWAP")];

    expect(watchlistOwner(items, "BTC-USDT")).toBe("BTC-USDT-SWAP");
    expect(watchlistOwner(items, "BTC-USDT-SWAP")).toBe("BTC-USDT-SWAP");
    expect(stripSwapSuffix("BTC-USDT-SWAP")).toBe("BTC-USDT");
    expect(stripSwapSuffix("BTC-USDT")).toBe("BTC-USDT");
  });

  it("归属不到任何自选标的的提醒不计入汇总", () => {
    const items = [makeItem("BTC-USDT-SWAP")];
    const digest = buildPendingDigest(items, [
      makeAlert("al_in", "持仓缺少止损", "BTC-USDT"),
      makeAlert("al_out", "持仓缺少止损", "NOTINLIST-USDT"),
    ]);

    expect(digest.total).toBe(1);
    expect(digest.entries.map((entry) => entry.key)).toEqual(["alert:al_in"]);
    expect(watchlistOwner(items, "NOTINLIST-USDT")).toBeNull();
  });

  it("没有 instrument_id 的提醒不算归属", () => {
    const items = [makeItem("BTC-USDT-SWAP")];
    const digest = buildPendingDigest(items, [makeAlert("al_null", "数据延迟", null)]);

    expect(digest.total).toBe(0);
    expect(watchlistOwner(items, null)).toBeNull();
  });

  it("同一产品的现货与永续同时存在时精确匹配优先", () => {
    const items = [makeItem("BTC-USDT", { instType: "SPOT" }), makeItem("BTC-USDT-SWAP")];
    const digest = buildPendingDigest(items, [makeAlert("al_spot", "持仓缺少止损", "BTC-USDT")]);

    expect(watchlistOwner(items, "BTC-USDT")).toBe("BTC-USDT");
    expect(watchlistOwner(items, "BTC-USDT-SWAP")).toBe("BTC-USDT-SWAP");
    expect(digest.entries[0].label).toBe("BTC-USDT");
  });
});

describe("分组联动（AC9）", () => {
  const items = [
    makeItem("AAPL-USDT-SWAP", { change: "1" }),
    makeItem("NVDA-USDT-SWAP", { change: null }),
    makeItem("BTC-USDT-SWAP", { change: "3", assetType: "crypto" }),
  ];
  const alerts = [
    makeAlert("al_aapl", "持仓缺少止损", "AAPL-USDT"),
    makeAlert("al_btc", "持仓缺少止损", "BTC-USDT"),
  ];

  it("选中美股后汇总只统计美股标的与它们的提醒", () => {
    const usStocks = items.filter((item) => matchesCategory(item.instrument, "stock_swap"));
    const aggregate = aggregateWatchlist(usStocks);
    const pending = buildPendingDigest(usStocks, alerts);

    expect(usStocks).toHaveLength(2);
    expect(aggregate.total).toBe(2);
    expect(aggregate.distribution).toEqual({ up: 1, down: 0, flat: 1 });
    // 三段之和等于当前分组的标的数。
    expect(
      aggregate.distribution.up + aggregate.distribution.down + aggregate.distribution.flat,
    ).toBe(usStocks.length);
    expect(pending.entries.map((entry) => entry.key)).toEqual(["alert:al_aapl"]);
  });

  it("切回全部后恢复全量", () => {
    const aggregate = aggregateWatchlist(items);
    const pending = buildPendingDigest(items, alerts);

    expect(aggregate.total).toBe(3);
    expect(aggregate.distribution).toEqual({ up: 2, down: 0, flat: 1 });
    expect(pending.total).toBe(2);
  });
});
