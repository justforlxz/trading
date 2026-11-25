import { summarizeHits, type RiskExposure } from "../../lib/risk";
import { cn } from "../../lib/utils";

export type HitStripViewProps = {
  exposure: RiskExposure | null;
  onOpenSettings: () => void;
};

/**
 * 风控命中条：把 `GET /api/risk/exposure` 的规则结果压成几个徽标。
 *
 * 只数命中，不重新判定；没有命中时显示「无」，而不是把整条藏起来——藏起来会让人
 * 以为风控没跑。
 */
export function HitStripView({ exposure, onOpenSettings }: HitStripViewProps) {
  const hits = summarizeHits(exposure);

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-xs shadow-sm">
      <span className="text-muted-foreground">风控命中</span>
      {exposure === null ? (
        <span className="text-[11px] text-muted-foreground">读取中…</span>
      ) : hits.length === 0 ? (
        <span className="text-[11px] text-muted-foreground">无</span>
      ) : (
        hits.map((hit) => (
          <span
            key={hit.id}
            className={cn(
              "rounded-full border px-2 py-0.5 text-[11px] font-medium",
              hit.tone,
            )}
            data-hit={hit.id}
          >
            {hit.label}
          </span>
        ))
      )}
      <button
        type="button"
        onClick={onOpenSettings}
        className="ml-auto text-[11px] text-muted-foreground underline underline-offset-4 hover:text-foreground"
      >
        调整规则
      </button>
    </div>
  );
}

export default HitStripView;
