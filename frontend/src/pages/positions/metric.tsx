import { cn } from "../../lib/utils";

/** 持仓页与账户卡共用的一项指标块；样式差异只由 `size` 决定。 */
export function Metric({
  label,
  value,
  note,
  tone,
  size = "base",
}: {
  label: string;
  value: string;
  note?: string;
  tone?: string;
  size?: "base" | "lg";
}) {
  return (
    <div className="min-w-0 rounded-md border px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "mt-1 truncate font-mono tabular-nums",
          size === "lg" ? "text-lg" : "text-base",
          tone,
        )}
        title={value}
      >
        {value}
      </dd>
      {note ? <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{note}</p> : null}
    </div>
  );
}
