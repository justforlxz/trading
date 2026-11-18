import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  searchInstruments: vi.fn(),
  addWatchlistItem: vi.fn(),
  fetchInstrumentAnalysis: vi.fn(),
  syncInstrument: vi.fn(),
}));

import {
  addWatchlistItem,
  fetchInstrumentAnalysis,
  searchInstruments,
  syncInstrument,
} from "./api";
import { searchWatchlist } from "./watchlist-search";

const RESULT = {
  items: [
    {
      inst_id: "SPCX-USDT",
      inst_type: "SPOT" as const,
      product_key: "SPCX",
      asset_type: "tokenized_equity" as const,
      base_currency: "XSPCX",
      quote_currency: "USDT",
    },
  ],
};

describe("searchWatchlist", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(searchInstruments).mockResolvedValue(RESULT);
  });

  it("只调用 searchInstruments，不预取行情、分析、同步或加入自选", async () => {
    const items = await searchWatchlist("SPCX");

    expect(items).toBe(RESULT.items);
    expect(searchInstruments).toHaveBeenCalledTimes(1);
    expect(searchInstruments).toHaveBeenCalledWith("SPCX");
    expect(addWatchlistItem).not.toHaveBeenCalled();
    expect(fetchInstrumentAnalysis).not.toHaveBeenCalled();
    expect(syncInstrument).not.toHaveBeenCalled();
  });
});
