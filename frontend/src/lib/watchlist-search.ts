import { searchInstruments, type InstrumentRef } from "./api";

/**
 * 搜索框提交的唯一网络调用：只查标的表，不预取行情、分析或同步。
 *
 * 抽成纯编排函数是为了让测试能直接断言「除了 searchInstruments 之外什么都没调」。
 */
export async function searchWatchlist(query: string): Promise<InstrumentRef[]> {
  const response = await searchInstruments(query);
  return response.items;
}
