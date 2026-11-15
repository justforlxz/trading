import { describe, expect, it } from "vitest";

import type {
  BacktestRunSummary,
  InstrumentAnalysisLinkedBacktest,
  InstrumentStrategy,
  StrategyVersionDetail,
} from "./api";
import {
  backtestsForVersions,
  categoryLabel,
  dataSourceLabel,
  directionLabel,
  joinInstrumentIds,
  launchVersionsForInstrument,
  linkedStrategyState,
  parameterRows,
  parseJsonObject,
  parseOptionalJsonObject,
  preferredLaunchVersionId,
  prettyJson,
  splitInstrumentIds,
  statusLabel,
  versionLabel,
} from "./strategies";

function run(runId: string, versionId: string | null): BacktestRunSummary {
  return { run_id: runId, strategy_version_id: versionId } as BacktestRunSummary;
}

describe("策略标签", () => {
  it("已知取值翻成中文，未知取值原样返回", () => {
    expect(categoryLabel("directional")).toBe("方向性（directional）");
    expect(categoryLabel("custom")).toBe("custom");
    expect(statusLabel("validated")).toBe("已验证");
    expect(directionLabel("long_short")).toBe("多空双向");
    expect(dataSourceLabel("okx_swap")).toBe("OKX 永续（okx_swap）");
    expect(versionLabel(3)).toBe("v3");
  });
});

describe("策略输入的 JSON 校验", () => {
  it("接受 JSON 对象并原样返回", () => {
    expect(parseJsonObject('{"fast": 20}', "参数")).toEqual({ fast: 20 });
  });

  it("拒绝空值、无效 JSON、数组和 null", () => {
    expect(() => parseJsonObject("", "参数")).toThrow("参数不能为空");
    expect(() => parseJsonObject("{", "参数")).toThrow("参数不是有效的 JSON");
    expect(() => parseJsonObject("[]", "参数")).toThrow("参数必须是 JSON 对象");
    expect(() => parseJsonObject("null", "参数")).toThrow("参数必须是 JSON 对象");
  });

  it("可选字段留空时返回 null", () => {
    expect(parseOptionalJsonObject("  ", "仓位规则")).toBeNull();
    expect(parseOptionalJsonObject('{"weight": 0.5}', "仓位规则")).toEqual({ weight: 0.5 });
  });
});

describe("标的标识与参数展示", () => {
  it("按空白或逗号拆分、去重并保持顺序", () => {
    expect(splitInstrumentIds(" AAPL-USDT-SWAP, BTC-USDT-SWAP\nAAPL-USDT-SWAP ")).toEqual([
      "AAPL-USDT-SWAP",
      "BTC-USDT-SWAP",
    ]);
    expect(joinInstrumentIds(["AAPL-USDT-SWAP", "BTC-USDT-SWAP"])).toBe(
      "AAPL-USDT-SWAP\nBTC-USDT-SWAP",
    );
  });

  it("参数按键名排序，字符串不加引号", () => {
    expect(parameterRows({ slow: 60, fast: 20, mode: "trend" })).toEqual([
      { key: "fast", value: "20" },
      { key: "mode", value: "trend" },
      { key: "slow", value: "60" },
    ]);
  });

  it("JSON 原样缩进展示，空值返回空字符串", () => {
    expect(prettyJson({ fast: 20 })).toBe('{\n  "fast": 20\n}');
    expect(prettyJson(null)).toBe("");
  });
});

describe("策略回测记录过滤", () => {
  it("只保留属于该策略版本且带版本标识的记录，顺序不变", () => {
    const runs = [run("bt_1", "sv_1"), run("bt_2", "sv_2"), run("bt_3", null), run("bt_4", "sv_9")];

    expect(backtestsForVersions(runs, ["sv_2", "sv_1"]).map((item) => item.run_id)).toEqual([
      "bt_1",
      "bt_2",
    ]);
  });
});

function version(
  versionId: string,
  versionNumber: number,
  instrumentIds: string[],
): StrategyVersionDetail {
  return {
    version_id: versionId,
    strategy_id: "st_1",
    version: versionNumber,
    timeframe: "1d",
    direction: "long_only",
    rule_json: {},
    parameters: {},
    position_sizing: null,
    cost_model: null,
    change_note: null,
    instrument_ids: instrumentIds,
    created_at: "2026-11-10T00:00:00Z",
  };
}

describe("详情页联动回测", () => {
  it("只保留包含当前标的的策略版本，保持接口顺序", () => {
    const versions = [
      version("sv_3", 3, ["AAPL-USDT-SWAP"]),
      version("sv_2", 2, ["BTC-USDT-SWAP"]),
      version("sv_1", 1, ["AAPL-USDT-SWAP", "BTC-USDT-SWAP"]),
    ];

    expect(
      launchVersionsForInstrument(versions, "AAPL-USDT-SWAP").map((item) => item.version_id),
    ).toEqual(["sv_3", "sv_1"]);
  });

  it("默认选中最近回测使用的版本，找不到时回落到第一个", () => {
    const versions = [
      version("sv_2", 2, ["AAPL-USDT-SWAP"]),
      version("sv_1", 1, ["AAPL-USDT-SWAP"]),
    ];

    expect(preferredLaunchVersionId(versions, "sv_1")).toBe("sv_1");
    expect(preferredLaunchVersionId(versions, "sv_9")).toBe("sv_2");
    expect(preferredLaunchVersionId([], "sv_1")).toBe("");
  });

  it("空态区分加载中、没有关联策略、没有近 30 天回测", () => {
    const strategy = { strategy_id: "st_1" } as InstrumentStrategy;
    const linkedBacktest = { run_id: "bt_1" } as InstrumentAnalysisLinkedBacktest;

    expect(linkedStrategyState(null, [])).toBe("loading");
    expect(linkedStrategyState([], [])).toBe("no_strategies");
    expect(linkedStrategyState([strategy], [])).toBe("no_recent_backtests");
    expect(linkedStrategyState([strategy], [linkedBacktest])).toBe("ready");
    expect(linkedStrategyState(null, [linkedBacktest])).toBe("ready");
  });

  it("标的已从全部策略版本移除但仍有回测时，仍显示回测行", () => {
    const linkedBacktest = { run_id: "bt_1" } as InstrumentAnalysisLinkedBacktest;

    expect(linkedStrategyState([], [linkedBacktest])).toBe("ready");
  });
});
