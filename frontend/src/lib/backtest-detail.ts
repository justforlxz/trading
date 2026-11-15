/**
 * 回测详情页的纯展示辅助。
 *
 * 这里只做三件不改数值的事：把接口返回的形状整理成图表组件能画的形状、按建仓日期
 * 选择行、把比值改写成百分数文案。收益、回撤、胜率等指标全部由后端算好。
 */

import type {
  BacktestChartResponse,
  BacktestEquityPoint,
  BacktestReplayPoint,
  BacktestTradeRow,
} from "./api";
import type { CandlestickInput } from "./candlestick";
import type { ClosePoint } from "./chart";

/**
 * 后端以比值返回的胜率 → 固定两位小数的百分比文案，不带正负号。
 *
 * 与 `display.percentValue` 的分工：那个函数用于带方向的涨跌值，会补正号并去掉
 * 末尾的零；胜率没有方向，固定两位小数更便于横向比较。
 */
export function ratioToPercent(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const parsed = Number(value.trim());
  if (!Number.isFinite(parsed)) return value;
  return `${(parsed * 100).toFixed(2)}%`;
}

/** 回测 K 线 → 蜡烛图输入；缺口列表为空，因为接口没有返回缺口。 */
export function backtestChartInput(chart: BacktestChartResponse): CandlestickInput {
  return {
    candles: chart.candles.map((candle) => ({
      open_time: candle.time,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
      volume: candle.volume,
      is_closed: candle.is_complete,
      data_source: candle.source,
    })),
    overlays: chart.overlays,
    gaps: [],
    markers: chart.markers,
  };
}

/** 标记与 K 线的对应关系：没有对应 K 线的标记不会被画出来。 */
export function chartMarkerCounts(chart: BacktestChartResponse): {
  entries: number;
  exits: number;
  unmatched: number;
} {
  const times = new Set(chart.candles.map((candle) => candle.time));
  let entries = 0;
  let exits = 0;
  let unmatched = 0;
  for (const marker of chart.markers) {
    if (!times.has(marker.time)) {
      unmatched += 1;
    } else if (marker.kind === "entry") {
      entries += 1;
    } else {
      exits += 1;
    }
  }
  return { entries, exits, unmatched };
}

/** 净值序列 → 折线点；数值原样保留。 */
export function equityLinePoints(points: BacktestEquityPoint[]): ClosePoint[] {
  return points.map((point) => ({ time: point.time, price: point.equity }));
}

/** 回撤序列 → 折线点；后端比值乘 100 供纵轴显示，标签注明单位是百分比。 */
export function drawdownLinePoints(points: BacktestEquityPoint[]): ClosePoint[] {
  return points.map((point) => {
    const parsed = Number(point.drawdown.trim());
    return {
      time: point.time,
      price: Number.isFinite(parsed) ? (parsed * 100).toFixed(4) : point.drawdown,
    };
  });
}

/** 回放到当前帧为止的收盘价；没有收盘价的点不补造。 */
export function replayClosePoints(points: BacktestReplayPoint[], frame: number): ClosePoint[] {
  return points
    .slice(0, Math.max(0, frame + 1))
    .filter((point) => point.close !== null && point.close !== undefined && point.close !== "")
    .map((point) => ({ time: point.time, price: point.close as string }));
}

/** 建仓日期筛选；日期是 UTC 日期，与接口时间戳的前 10 位直接比较。 */
export function filterTradesByEntryDate(
  trades: BacktestTradeRow[],
  from: string,
  to: string,
): BacktestTradeRow[] {
  if (from === "" && to === "") return trades;
  return trades.filter((trade) => dateInRange(trade.entry_time.slice(0, 10), from, to));
}

function dateInRange(value: string, from: string, to: string): boolean {
  if (from !== "" && value < from) return false;
  if (to !== "" && value > to) return false;
  return true;
}

type CsvRow = { raw: string; fields: string[] };

/** 逐行保留原文的 CSV 拆分；只用于按建仓日期裁剪，不重新格式化任何单元格。 */
function parseCsvRows(text: string): CsvRow[] {
  const rows: CsvRow[] = [];
  let fields: string[] = [];
  let field = "";
  let raw = "";
  let quoted = false;
  let index = 0;

  while (index < text.length) {
    const char = text[index];
    raw += char;
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          raw += '"';
          index += 2;
          continue;
        }
        quoted = false;
        index += 1;
        continue;
      }
      field += char;
      index += 1;
      continue;
    }
    if (char === '"') {
      quoted = true;
      index += 1;
      continue;
    }
    if (char === ",") {
      fields.push(field);
      field = "";
      index += 1;
      continue;
    }
    if (char === "\r") {
      index += 1;
      continue;
    }
    if (char === "\n") {
      fields.push(field);
      let line = raw.slice(0, -1);
      if (line.endsWith("\r")) line = line.slice(0, -1);
      rows.push({ raw: line, fields });
      fields = [];
      field = "";
      raw = "";
      index += 1;
      continue;
    }
    field += char;
    index += 1;
  }

  if (field !== "" || fields.length > 0) {
    fields.push(field);
    rows.push({ raw, fields });
  }
  return rows;
}

/**
 * 按建仓日期裁剪后端 CSV。
 *
 * 后端导出接口不支持时间条件，因此时间筛选必须在这里完成；保留每一行的原始文本，
 * 保证导出的行与页面上筛选后的行一一对应。没有时间条件时原文返回。
 */
export function filterCsvByEntryDate(csvText: string, from: string, to: string): string {
  if (from === "" && to === "") return csvText;
  const rows = parseCsvRows(csvText);
  if (rows.length === 0) return csvText;
  const [header, ...body] = rows;
  // 第 3 列是「开仓时间」，列顺序由后端契约固定。
  const kept = body.filter((row) => {
    const entry = row.fields[2] ?? "";
    return dateInRange(entry.slice(0, 10), from, to);
  });
  return [header.raw, ...kept.map((row) => row.raw)].join("\r\n") + "\r\n";
}
