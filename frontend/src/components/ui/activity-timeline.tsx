import { activityEventLabel, type ActivityView } from "../../lib/activity";
import { formatBeijingTime } from "../../lib/display";

export type ActivityTimelineProps = {
  items: ReadonlyArray<ActivityView>;
  loading?: boolean;
  emptyText?: string;
};

/**
 * 活动时间线：首页卡片与记录页共用同一套条目标注。
 * 文案只使用接口返回的 `summary`，事件类型只做中文标签。
 */
export function ActivityTimeline({
  items,
  loading = false,
  emptyText = "没有最近活动。",
}: ActivityTimelineProps) {
  if (loading && items.length === 0) {
    return <p className="text-sm text-muted-foreground">正在加载活动流水…</p>;
  }
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyText}</p>;
  }
  return (
    <ol className="space-y-2.5">
      {items.map((item) => (
        <li key={item.id} className="flex gap-3" data-activity-id={item.id}>
          <span
            aria-hidden="true"
            className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/60"
          />
          <div className="min-w-0 flex-1">
            <p className="break-words text-sm leading-5">{item.summary}</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {activityEventLabel(item.event_type)} · {formatBeijingTime(item.created_at)}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
