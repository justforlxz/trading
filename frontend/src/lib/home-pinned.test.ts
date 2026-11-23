import { describe, expect, it } from "vitest";

import type { WatchlistItem } from "./api";
import type { PinnedCandidate } from "./home-pinned";
import {
  PINNED_LIMIT,
  isPinnedFull,
  pinnedCandidates,
  pinnedCardRows,
  pinnedCountText,
  pinnedItems,
  submittablePinned,
  togglePinned,
} from "./home-pinned";

function items(ids: readonly string[]): { inst_id: string; display_symbol: string }[] {
  return ids.map((instId) => ({ inst_id: instId, display_symbol: instId.replace(/-USDT.*/, "") }));
}

describe("首页关注列表置顶", () => {
  it("按置顶顺序取行，而不是按自选顺序", () => {
    const watchlist = items(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]);

    const picked = pinnedItems(watchlist, ["SOL-USDT-SWAP", "BTC-USDT-SWAP"]);

    expect(picked.map((item) => item.inst_id)).toEqual(["SOL-USDT-SWAP", "BTC-USDT-SWAP"]);
  });

  it("不在自选里的置顶项直接跳过，不凭空造行", () => {
    const watchlist = items(["BTC-USDT-SWAP"]);

    const picked = pinnedItems(watchlist, ["BTC-USDT-SWAP", "GONE-USDT-SWAP"]);

    expect(picked.map((item) => item.inst_id)).toEqual(["BTC-USDT-SWAP"]);
  });

  it("没有置顶项时没有任何行", () => {
    expect(pinnedItems(items(["BTC-USDT-SWAP"]), [])).toEqual([]);
  });

  it("勾选追加到末尾，取消只移除自己", () => {
    expect(togglePinned([], "A")).toEqual(["A"]);
    expect(togglePinned(["A"], "B")).toEqual(["A", "B"]);
    expect(togglePinned(["A", "B"], "A")).toEqual(["B"]);
  });

  it("已满 5 个时再勾选保持原样", () => {
    const full = ["A", "B", "C", "D", "E"];

    expect(full).toHaveLength(PINNED_LIMIT);
    expect(togglePinned(full, "F")).toEqual(full);
    expect(isPinnedFull(full)).toBe(true);
    expect(isPinnedFull(["A", "B", "C", "D"])).toBe(false);
  });

  it("取消已有项在满额时仍然允许", () => {
    expect(togglePinned(["A", "B", "C", "D", "E"], "C")).toEqual(["A", "B", "D", "E"]);
  });

  it("数量文案", () => {
    expect(pinnedCountText(0)).toBe(`已选 0/${PINNED_LIMIT}`);
    expect(pinnedCountText(3)).toBe("已选 3/5");
  });
});

describe("弹窗候选", () => {
  it("整份自选都成为候选，不只是首页汇总里的前五行", () => {
    const items = [1, 2, 3, 4, 5, 6, 7].map(
      (index) =>
        ({
          instrument: { inst_id: `X${index}-USDT`, product_key: `X${index}` },
          group: index % 2 === 0 ? "股票" : "默认",
          last_price: `${index}0`,
        }) as unknown as WatchlistItem,
    );

    const candidates = pinnedCandidates(items);

    expect(candidates).toHaveLength(7);
    expect(candidates[5]).toEqual({
      inst_id: "X6-USDT",
      display_symbol: "X6",
      name: "X6",
      detail: "股票",
      last_price: "60",
      change_pct_24h: undefined,
      rsi_14: undefined,
      trend: undefined,
    });
  });

  it("空自选得到空候选", () => {
    expect(pinnedCandidates([])).toEqual([]);
  });
});

describe("卡片行（不依赖首页汇总五行）", () => {
  const candidate = (instId: string, overrides: Partial<PinnedCandidate> = {}): PinnedCandidate => ({
    inst_id: instId,
    display_symbol: instId.replace(/-USDT.*/, ""),
    name: instId.replace(/-USDT.*/, ""),
    detail: "默认",
    last_price: "1",
    change_pct_24h: "0.5",
    rsi_14: "50",
    trend: "bullish",
    ...overrides,
  });

  it("置顶项不在汇总五行里也照样出行（保存后立刻渲染的前提）", () => {
    const candidates = ["A", "B", "C", "D", "E", "F", "G"].map((id) => candidate(`${id}-USDT`));
    const summaryRows = candidates.slice(0, 5);

    const rows = pinnedCardRows(candidates, summaryRows, ["G-USDT"]);

    expect(rows.map((row) => row.inst_id)).toEqual(["G-USDT"]);
  });

  it("汇总里有的行用汇总的数值覆盖自选快照（推送会写回汇总）", () => {
    const candidates = [candidate("A-USDT", { last_price: "100", change_pct_24h: "0.1" })];
    const summaryRows = [
      {
        inst_id: "A-USDT",
        display_symbol: "A-USDT",
        name: "A",
        last_price: "123.4",
        change_pct_24h: "1.86",
        rsi_14: "61.4",
        trend: "bearish" as const,
        data_status: "ok" as const,
      },
    ];

    const [row] = pinnedCardRows(candidates, summaryRows, ["A-USDT"]);

    expect(row.last_price).toBe("123.4");
    expect(row.change_pct_24h).toBe("1.86");
    expect(row.rsi_14).toBe("61.4");
    expect(row.trend).toBe("bearish");
    expect(row.display_symbol).toBe("A-USDT");
  });

  it("既不在自选也不在汇总里的置顶项不造行", () => {
    const rows = pinnedCardRows([candidate("A-USDT")], [], ["A-USDT", "GONE-USDT"]);

    expect(rows.map((row) => row.inst_id)).toEqual(["A-USDT"]);
  });
});

describe("提交给接口的置顶清单", () => {
  it("只保留当前自选里的标识：看不见的项由服务端补回，不能一起提交", () => {
    const candidates = [{ inst_id: "BTC-USDT" }, { inst_id: "AAPL-USDT" }];

    const payload = submittablePinned(["GONE-USDT", "BTC-USDT", "AAPL-USDT"], candidates);

    expect(payload).toEqual(["BTC-USDT", "AAPL-USDT"]);
  });

  it("保持草稿里的相对顺序", () => {
    const candidates = [{ inst_id: "A" }, { inst_id: "B" }, { inst_id: "C" }];

    expect(submittablePinned(["C", "A"], candidates)).toEqual(["C", "A"]);
  });

  it("候选为空时提交空清单（此时保存按钮本来就禁用）", () => {
    expect(submittablePinned(["BTC-USDT"], [])).toEqual([]);
  });
});
