import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { BacktestLeg } from "../../lib/api";
import { signedTone, signedValue } from "../../lib/display";
import { cn } from "../../lib/utils";
import { directionLabel, directionTone, formatMoment } from "./format";

const HEADERS = [
  "产品键",
  "标的",
  "方向",
  "笔数",
  "开仓",
  "平仓",
  "手续费",
  "盈亏",
  "贡献",
];

export type BacktestLegsProps = {
  legs: BacktestLeg[];
};

/**
 * 逐腿明细：每条腿的方向、第一笔开仓到最后一笔平仓、成本与盈亏。
 *
 * 贡献是该腿已实现盈亏占初始资金的百分比；回测结束仍未平掉的仓位只在资金曲线里。
 */
export function BacktestLegs({ legs }: BacktestLegsProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>逐腿明细</CardTitle>
        <CardDescription>
          每条腿的方向、第一笔开仓到最后一笔平仓、成本与盈亏。各腿贡献相加可能小于总收益率，
          差的正是收盘仍未平仓部分的浮动盈亏。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {legs.length === 0 ? (
          <p className="text-sm text-muted-foreground">这次回测没有成交腿。</p>
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
                {legs.map((leg) => (
                  <tr
                    key={`${leg.product_key}-${leg.side}`}
                    className="border-b last:border-b-0"
                  >
                    <td className="py-2 pr-3 font-mono text-xs">{leg.product_key}</td>
                    <td className="py-2 pr-3">{leg.inst_id}</td>
                    <td className="py-2 pr-3">
                      <span
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-xs",
                          directionTone(leg.side),
                        )}
                      >
                        {directionLabel(leg.side)}
                      </span>
                    </td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{leg.trade_count}</td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {formatMoment(leg.entry_time)}
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {formatMoment(leg.exit_time)}
                    </td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{leg.fee}</td>
                    <td className={cn("py-2 pr-3 font-mono tabular-nums", signedTone(leg.pnl))}>
                      {signedValue(leg.pnl)}
                    </td>
                    <td
                      className={cn(
                        "py-2 font-mono tabular-nums",
                        signedTone(leg.contribution_pct),
                      )}
                    >
                      {signedValue(leg.contribution_pct)}%
                    </td>
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
