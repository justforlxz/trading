import type { StreamLiveness } from "../../lib/stream";
import { cn } from "../../lib/utils";

/** 页面级提示：推送断开时明确说明当前值是最后已知值。 */
export function StreamNotice({
  liveness,
  subject,
}: {
  liveness: StreamLiveness;
  subject: string;
}) {
  if (liveness === "live") return null;
  const stale = liveness === "stale";
  return (
    <p
      role="status"
      className={cn(
        "rounded-md border px-3 py-2 text-sm",
        stale
          ? "border-amber-600/40 bg-amber-500/5 text-amber-700 dark:text-amber-400"
          : "border-border bg-muted/40 text-muted-foreground",
      )}
    >
      {stale
        ? `实时推送已断开：${subject}为最后已知值，不是实时数据。`
        : `正在连接实时推送：${subject}暂为 HTTP 快照。`}
    </p>
  );
}

/** 数据旁的短标记，避免只看页面提示时把旧值当成实时值。 */
export function StreamTag({ liveness }: { liveness: StreamLiveness }) {
  if (liveness === "live") return null;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px]",
        liveness === "stale"
          ? "border-amber-600/40 text-amber-700 dark:text-amber-400"
          : "border-border text-muted-foreground",
      )}
    >
      {liveness === "stale" ? "已断开" : "连接中"}
    </span>
  );
}
