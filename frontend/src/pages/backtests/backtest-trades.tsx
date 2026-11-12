import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { BacktestTradeRow } from "../../lib/api";
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
  "盈亏",
  "原因",
];

export type BacktestTradesProps = {
  trades: BacktestTradeRow[];
};

/** 逐笔交易：每次完整交易的建仓与平仓时刻、价格、数量、手续费与盈亏。 */
export function BacktestTrades({ trades }: BacktestTradesProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>逐笔交易</CardTitle>
        <CardDescription>
          每次完整交易的建仓与平仓时刻、价格、数量、手续费与盈亏，共 {trades.length} 笔。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {trades.length === 0 ? (
          <p className="text-sm text-muted-foreground">这次回测没有成交。</p>
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
                {trades.map((trade) => (
                  <tr key={trade.trade_id} className="border-b last:border-b-0">
                    <td className="py-2 pr-3">{directionLabel(trade.side)}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{trade.qty}</td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {formatMoment(trade.entry_time)}
                    </td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{trade.entry_price}</td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {formatMoment(trade.exit_time)}
                    </td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{trade.exit_price}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{trade.fee}</td>
                    <td className={cn("py-2 pr-3 font-mono tabular-nums", signedTone(trade.pnl))}>
                      {signedValue(trade.pnl)}
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
