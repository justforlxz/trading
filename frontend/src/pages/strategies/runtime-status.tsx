import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { StrategyRuntimeResponse } from "../../lib/api";
import { formatBeijingTime } from "../../lib/display";
import {
  autoExecutionLabel,
  marketSubscriptionLabel,
  signalScanLabel,
  type MarketSubscriptionStatus,
} from "../../lib/strategy-runtime";
import { cn } from "../../lib/utils";

export type StrategyRuntimeStatusCardProps = {
  runtime: StrategyRuntimeResponse | null;
  loading: boolean;
  error: string | null;
  marketSubscription: MarketSubscriptionStatus;
};

function StatusValue({ children, tone }: { children: string; tone?: string }) {
  return <span className={cn("text-sm font-medium", tone)}>{children}</span>;
}

/**
 * 策略页运行状态：信号扫描、行情订阅、自动执行与最近检查时间。
 *
 * 信号扫描与自动执行读取后端运行状态接口；行情订阅只读取推送层的数据源状态；
 * 检查时间使用后端返回的 `checked_at`，页面不按当前时间推算。
 */
export function StrategyRuntimeStatusCard({
  runtime,
  loading,
  error,
  marketSubscription,
}: StrategyRuntimeStatusCardProps) {
  const pendingText = loading ? "读取中" : error ? "读取失败" : "未提供";
  const signalValue = runtime === null ? pendingText : signalScanLabel(runtime.signal_scan);
  const autoValue = runtime === null ? pendingText : autoExecutionLabel(runtime.auto_execution);
  const checkedValue =
    runtime === null ? pendingText : `${formatBeijingTime(runtime.checked_at)}（北京时间）`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>运行状态</CardTitle>
        <CardDescription>
          信号扫描、行情订阅、自动执行与最近检查时间。自动执行开关只保存状态，本版本不产生真实订单。
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="space-y-1 rounded-md border p-3">
          <p className="text-xs text-muted-foreground">信号扫描</p>
          <StatusValue
            tone={runtime?.signal_scan.status === "not_implemented" ? "text-muted-foreground" : undefined}
          >
            {signalValue}
          </StatusValue>
          <p className="text-xs text-muted-foreground">
            {runtime?.signal_scan.detail ?? error ?? "等待后端返回信号扫描状态"}
          </p>
        </div>

        <div className="space-y-1 rounded-md border p-3">
          <p className="text-xs text-muted-foreground">行情订阅</p>
          <StatusValue>{marketSubscriptionLabel(marketSubscription)}</StatusValue>
          <p className="text-xs text-muted-foreground">来自 /api/stream 推送层</p>
        </div>

        <div className="space-y-1 rounded-md border p-3">
          <p className="text-xs text-muted-foreground">自动执行</p>
          <StatusValue tone={runtime?.auto_execution.enabled ? "text-amber-700 dark:text-amber-400" : undefined}>
            {autoValue}
          </StatusValue>
          <p className="text-xs text-muted-foreground">
            {runtime?.auto_execution.detail ?? error ?? "等待后端返回自动执行状态"}
          </p>
        </div>

        <div className="space-y-1 rounded-md border p-3">
          <p className="text-xs text-muted-foreground">最近检查时间</p>
          <StatusValue>{checkedValue}</StatusValue>
          <p className="text-xs text-muted-foreground">由后端返回，不在前端推算</p>
        </div>
      </CardContent>
    </Card>
  );
}
