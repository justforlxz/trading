import { Button } from "./button";
import { formatBeijingTime } from "../../lib/display";
import {
  alertTypeLabel,
  severityLabel,
  severityTone,
  sortAlertsBySeverity,
  type AlertStatusUpdate,
  type AlertView,
} from "../../lib/alerts";
import { cn } from "../../lib/utils";

export type AlertListProps = {
  items: ReadonlyArray<AlertView>;
  onResolve?: (alertId: string, status: AlertStatusUpdate) => void;
  resolvingId?: string | null;
  emptyText?: string;
};

/**
 * 提醒列表：内容全部来自接口，确认与忽略直接调用 PATCH，不修改标题或级别。
 */
export function AlertList({
  items,
  onResolve,
  resolvingId = null,
  emptyText = "没有待处理提醒。",
}: AlertListProps) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyText}</p>;
  }
  const ordered = sortAlertsBySeverity(items);
  return (
    <ul className="space-y-2">
      {ordered.map((item) => {
        const busy = resolvingId === item.id;
        return (
          <li key={item.id} className="rounded-md border px-3 py-2" data-alert-id={item.id}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-[11px]",
                    severityTone(item.severity),
                  )}
                >
                  {severityLabel(item.severity)}
                </span>
                <span className="break-words text-sm font-medium">{item.title}</span>
              </div>
              <time className="shrink-0 text-[11px] text-muted-foreground">
                {formatBeijingTime(item.triggered_at)}
              </time>
            </div>
            <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{item.detail}</p>
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <p className="text-[11px] text-muted-foreground">
                {alertTypeLabel(item.type)} · 规则 {item.rule_id}
                {item.instrument_id ? ` · 标的 ${item.instrument_id}` : ""}
              </p>
              {onResolve ? (
                <div className="flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => onResolve(item.id, "acknowledged")}
                  >
                    {busy ? "处理中…" : "确认"}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => onResolve(item.id, "ignored")}
                  >
                    忽略
                  </Button>
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
