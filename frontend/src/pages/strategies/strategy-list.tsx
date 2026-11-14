import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { StrategySummary } from "../../lib/api";
import { formatBeijingTime, signedTone, signedValue } from "../../lib/display";
import { categoryLabel, statusLabel, versionLabel } from "../../lib/strategies";
import { cn } from "../../lib/utils";

export type StrategyListPanelProps = {
  items: StrategySummary[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (strategyId: string) => void;
  onCreate: () => void;
};

/** 策略列表：只展示接口返回的当前版本、标的数量与最近一次回测摘要。 */
export function StrategyListPanel({
  items,
  selectedId,
  loading,
  onSelect,
  onCreate,
}: StrategyListPanelProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <CardTitle>策略列表</CardTitle>
          <span className="text-xs text-muted-foreground">本页 {items.length} 个策略</span>
        </div>
        <CardDescription>
          每个策略显示当前版本；编辑规则会生成新版本，旧版本和旧回测继续指向原来的输入。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button type="button" size="sm" onClick={onCreate}>
          新建策略
        </Button>

        {loading ? (
          <p className="text-sm text-muted-foreground">正在加载策略…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            还没有用户策略。新建策略会同时创建第一个草稿版本。
          </p>
        ) : (
          <ul className="space-y-2">
            {items.map((item) => {
              const latest = item.latest_backtest;
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(item.id)}
                    aria-current={item.id === selectedId ? "true" : undefined}
                    className={cn(
                      "w-full rounded-lg border p-3 text-left transition-colors hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      item.id === selectedId && "bg-accent/50 ring-2 ring-ring",
                    )}
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="text-sm font-medium">{item.name}</span>
                      <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                        {statusLabel(item.status)}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {categoryLabel(item.category)} · 当前 {versionLabel(item.current_version)} ·{" "}
                      {item.instrument_count} 个标的 · {item.timeframe}
                    </p>
                    {latest ? (
                      <p className="mt-2 text-xs text-muted-foreground">
                        最近回测 {latest.backtest_start_date} ~ {latest.backtest_end_date} ·{" "}
                        {latest.trade_count} 笔 · 总收益率{" "}
                        <span className={cn("font-mono", signedTone(latest.total_return_pct))}>
                          {signedValue(latest.total_return_pct)}%
                        </span>{" "}
                        · 最大回撤 <span className="font-mono">{latest.max_drawdown_pct}%</span> ·{" "}
                        {formatBeijingTime(latest.created_at)}
                      </p>
                    ) : (
                      <p className="mt-2 text-xs text-muted-foreground">还没有回测记录。</p>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
