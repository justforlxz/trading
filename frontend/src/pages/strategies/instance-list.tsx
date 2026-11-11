import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { StrategyInstance } from "../../lib/api";
import { cn } from "../../lib/utils";

/** 生命周期阶段的中文说明；取值与契约的 `StrategyStatus` 一致。 */
const STATUS_LABELS: Record<string, string> = {
  opportunity_discovery: "机会发现",
  strategy_generation: "草稿",
  pending_review: "待人工审核",
  backtested: "已回测",
  validated: "已验证",
  paper_trading: "模拟交易",
  live_authorized: "已授权实盘",
  live_running: "实盘运行",
  rejected: "已驳回",
};

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export type InstanceListProps = {
  instances: StrategyInstance[];
  selectedId: string | null;
  busy: boolean;
  onReplay: (instance: StrategyInstance) => void;
  onToggle: (instance: StrategyInstance) => void;
  onDelete: (instance: StrategyInstance) => void;
};

/**
 * 实例列表：一条实例一张卡，不做密集表格。
 *
 * 阶段与启停分开展示：阶段是生命周期（只经审批状态机推进），`enabled` 只决定实例
 * 是否产出信号，两者不是一回事，界面上也不合并成一个状态。
 */
export function InstanceList({
  instances,
  selectedId,
  busy,
  onReplay,
  onToggle,
  onDelete,
}: InstanceListProps) {
  return (
    <Card>
      <CardHeader>
        <div className="space-y-1.5">
          <CardTitle>策略实例</CardTitle>
          <CardDescription>
            实例是可启停的用户配置；阶段推进走审批流程，本页只做启停与目标组合回放。
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        {instances.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            还没有实例。先在上面的模板里选中一个，再填写名称与标的。
          </p>
        ) : (
          <div className="grid gap-3">
            {instances.map((instance) => {
              const selected = instance.instance_id === selectedId;
              return (
                <div
                  key={instance.instance_id}
                  className={cn(
                    "rounded-lg border p-4 transition-colors",
                    selected && "border-primary bg-accent/40",
                  )}
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{instance.name}</span>
                      <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                        {statusLabel(instance.status)}
                      </span>
                      <span
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-xs",
                          instance.enabled
                            ? "border-emerald-600/40 text-emerald-600 dark:text-emerald-400"
                            : "border-border text-muted-foreground",
                        )}
                      >
                        {instance.enabled ? "已启用" : "已停用"}
                      </span>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {instance.strategy_id} · v{instance.strategy_version} · 周期 {instance.bar}
                    </span>
                  </div>

                  <p className="mt-2 text-xs leading-5 text-muted-foreground">
                    标的：{instance.inst_ids.join("、")}
                  </p>
                  <p className="text-xs leading-5 text-muted-foreground">
                    参数：
                    {Object.entries(instance.params)
                      .map(([key, value]) => `${key}=${String(value)}`)
                      .join(" · ")}
                  </p>

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant={selected ? "default" : "outline"}
                      onClick={() => onReplay(instance)}
                      disabled={busy}
                    >
                      回放
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() => onToggle(instance)}
                      disabled={busy}
                    >
                      {instance.enabled ? "停用" : "启用"}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="text-destructive hover:text-destructive"
                      onClick={() => onDelete(instance)}
                      disabled={busy}
                    >
                      删除
                    </Button>
                    <span className="ml-auto text-xs text-muted-foreground">
                      创建于 {instance.created_at}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
