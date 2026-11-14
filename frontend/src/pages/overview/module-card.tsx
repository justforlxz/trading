import { ArrowUpRight } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  asOfText,
  degradedReason,
  moduleStatusView,
  type DashboardSummary,
  type ModuleEnvelope,
} from "../../lib/dashboard";
import { cn } from "../../lib/utils";

export function StatusBadge({ status }: { status: string }) {
  const view = moduleStatusView(status);
  return (
    <span
      className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium", view.tone)}
    >
      {view.label}
    </span>
  );
}

/** 八个模块共用的卡片外壳：标题、状态、数据时间、跳转入口与降级文案。 */
export function ModuleCard({
  name,
  title,
  summary,
  module,
  streamed,
  to,
  className,
  children,
}: {
  name: string;
  title: string;
  summary: DashboardSummary;
  module: ModuleEnvelope<unknown>;
  streamed: boolean;
  to?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Card className={cn("min-w-0", className)} data-module={name} data-status={module.status}>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <div className="flex shrink-0 items-center gap-2">
            <StatusBadge status={module.status} />
            {to ? (
              <Link
                to={to}
                aria-label={`打开${title}所在页面`}
                className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
              >
                <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            ) : null}
          </div>
        </div>
        <CardDescription className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span>数据时间：{asOfText(module.as_of)}</span>
          <span aria-hidden="true">·</span>
          <span>{streamed ? "含推送数据" : "HTTP 快照"}</span>
        </CardDescription>
      </CardHeader>
      <CardContent>
        {module.data === null || module.data === undefined ? (
          <p
            role="status"
            className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground"
          >
            不可用（{degradedReason(summary, name, module)}）
          </p>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}
