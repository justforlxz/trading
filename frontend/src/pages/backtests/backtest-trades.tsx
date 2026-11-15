import { useCallback, useEffect, useState } from "react";

import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  ApiError,
  fetchBacktestTrades,
  fetchBacktestTradesCsv,
  type BacktestTradeFilters,
  type BacktestTradeRow,
} from "../../lib/api";
import { filterCsvByEntryDate, filterTradesByEntryDate } from "../../lib/backtest-detail";
import { signedTone, signedValue } from "../../lib/display";
import { cn } from "../../lib/utils";
import { directionLabel, formatMoment } from "./format";

const HEADERS = [
  "方向",
  "数量",
  "建仓",
  "建仓价",
  "平仓",
  "平仓价",
  "手续费",
  "价格盈亏",
  "净盈亏",
  "原因",
];

const PAGE_LIMIT = 500;

export type BacktestTradesViewProps = {
  side: string;
  result: string;
  entryFrom: string;
  entryTo: string;
  onSideChange: (value: string) => void;
  onResultChange: (value: string) => void;
  onEntryFromChange: (value: string) => void;
  onEntryToChange: (value: string) => void;
  onExport: () => void;
  loading: boolean;
  exporting: boolean;
  loadError: string | null;
  exportError: string | null;
  visible: BacktestTradeRow[];
};

export type BacktestTradesProps = {
  runId: string;
};

/** 后端支持的筛选条件：方向与盈亏结果；时间条件在本地按建仓日期裁剪。 */
function serverFilters(side: string, result: string): BacktestTradeFilters {
  return {
    ...(side === "long" || side === "short" ? { side } : {}),
    ...(result === "profit" || result === "loss" ? { result } : {}),
  };
}

/** 取完所有分页，保证表格行与导出的行使用同一份完整集合。 */
async function loadAllTrades(
  runId: string,
  filters: BacktestTradeFilters,
): Promise<BacktestTradeRow[]> {
  const collected: BacktestTradeRow[] = [];
  let offset = 0;
  let total = Number.POSITIVE_INFINITY;
  while (collected.length < total) {
    const page = await fetchBacktestTrades(runId, filters, PAGE_LIMIT, offset);
    collected.push(...page.items);
    total = page.total;
    if (page.items.length === 0) break;
    offset += page.items.length;
  }
  return collected;
}

/** 接口错误沿用后端文案；网络中断等非接口错误用中文提示，不直接显示浏览器原文。 */
function requestErrorMessage(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.message : fallback;
}

function downloadCsv(runId: string, csv: string): void {
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `backtest-${runId}-trades.csv`;
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/**
 * 交易明细的展示层。
 *
 * 加载中、读取失败、空结果与有数据四种状态互斥：读取失败时不再渲染旧数据，
 * 也不把失败写成「没有符合条件的交易」。导出失败单独提示，不影响已经加载的表格。
 */
export function BacktestTradesView({
  side,
  result,
  entryFrom,
  entryTo,
  onSideChange,
  onResultChange,
  onEntryFromChange,
  onEntryToChange,
  onExport,
  loading,
  exporting,
  loadError,
  exportError,
  visible,
}: BacktestTradesViewProps) {
  const countText = loading
    ? "正在读取交易明细。"
    : loadError !== null
      ? "交易明细读取失败。"
      : `当前筛选后共 ${visible.length} 笔。`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>逐笔交易</CardTitle>
        <CardDescription>
          每次完整交易的建仓与平仓时刻、价格、数量、手续费与盈亏；{countText}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">方向</span>
            <select
              className="h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={side}
              onChange={(event) => onSideChange(event.target.value)}
            >
              <option value="">全部</option>
              <option value="long">多头</option>
              <option value="short">空头</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">结果</span>
            <select
              className="h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={result}
              onChange={(event) => onResultChange(event.target.value)}
            >
              <option value="">全部</option>
              <option value="profit">盈利</option>
              <option value="loss">亏损</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">建仓日期起（UTC）</span>
            <input
              type="date"
              className="h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={entryFrom}
              onChange={(event) => onEntryFromChange(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">建仓日期止（UTC）</span>
            <input
              type="date"
              className="h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={entryTo}
              onChange={(event) => onEntryToChange(event.target.value)}
            />
          </label>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onExport}
            disabled={exporting || loading}
          >
            {exporting ? "正在导出…" : "导出当前筛选 CSV"}
          </Button>
        </div>

        {exportError !== null ? <p className="text-sm text-destructive">{exportError}</p> : null}

        {loading ? (
          <p className="py-8 text-center text-sm text-muted-foreground">正在读取交易明细…</p>
        ) : loadError !== null ? (
          <p className="py-8 text-center text-sm text-destructive">{loadError}</p>
        ) : visible.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            没有符合当前筛选条件的交易。
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  {HEADERS.map((header) => (
                    <th key={header} className="py-2 pr-3 font-medium last:pr-0">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((trade) => (
                  <tr key={trade.trade_id} className="border-b last:border-b-0">
                    <td className="py-2 pr-3">{directionLabel(trade.side)}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{trade.qty}</td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {formatMoment(trade.entry_time)}
                    </td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{trade.entry_price}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{formatMoment(trade.exit_time)}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{trade.exit_price}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{trade.fee}</td>
                    <td className={cn("py-2 pr-3 font-mono tabular-nums", signedTone(trade.pnl))}>
                      {signedValue(trade.pnl)}
                    </td>
                    <td
                      className={cn("py-2 pr-3 font-mono tabular-nums", signedTone(trade.net_pnl))}
                    >
                      {signedValue(trade.net_pnl)}
                    </td>
                    <td className="py-2 text-xs text-muted-foreground">{trade.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * 逐笔交易：方向、盈亏结果与建仓日期筛选，CSV 与当前筛选结果逐行一致。
 *
 * 方向与结果交给 `GET /backtests/{run_id}/trades`；建仓日期在本地裁剪，导出时对
 * `GET /backtests/{run_id}/trades.csv` 的原文套用同一规则，不再重新算数或补造行。
 * 筛选条件变化时先清空上一组数据，避免请求失败后继续展示不符合当前条件的旧行。
 */
export function BacktestTrades({ runId }: BacktestTradesProps) {
  const [side, setSide] = useState("");
  const [result, setResult] = useState("");
  const [entryFrom, setEntryFrom] = useState("");
  const [entryTo, setEntryTo] = useState("");
  const [trades, setTrades] = useState<BacktestTradeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError(null);
    setExportError(null);
    setTrades([]);
    loadAllTrades(runId, serverFilters(side, result))
      .then((rows) => {
        if (active) setTrades(rows);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setTrades([]);
        setLoadError(requestErrorMessage(reason, "交易明细加载失败，请检查网络后重试"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [runId, side, result]);

  const visible = filterTradesByEntryDate(trades, entryFrom, entryTo);

  const exportCsv = useCallback(() => {
    setExporting(true);
    setExportError(null);
    fetchBacktestTradesCsv(runId, serverFilters(side, result))
      .then((csv) => {
        downloadCsv(runId, filterCsvByEntryDate(csv, entryFrom, entryTo));
      })
      .catch((reason: unknown) => {
        setExportError(requestErrorMessage(reason, "CSV 导出失败，请检查网络后重试"));
      })
      .finally(() => setExporting(false));
  }, [runId, side, result, entryFrom, entryTo]);

  return (
    <BacktestTradesView
      side={side}
      result={result}
      entryFrom={entryFrom}
      entryTo={entryTo}
      onSideChange={setSide}
      onResultChange={setResult}
      onEntryFromChange={setEntryFrom}
      onEntryToChange={setEntryTo}
      onExport={exportCsv}
      loading={loading}
      exporting={exporting}
      loadError={loadError}
      exportError={exportError}
      visible={visible}
    />
  );
}
