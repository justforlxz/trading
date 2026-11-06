/** 机会卡片（驾驶舱）：分数、方向与前两条理由；点击进入单条详情。 */

import type { Opportunity } from "../../lib/api";
import { cn } from "../../lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import {
  directionLabels,
  evidenceNumber,
  formatNumber,
  formatPlainPercent,
  formatScore,
  formatSignedPercent,
  kindLabels,
} from "./format";

type Highlight = { label: string; value: string };

function highlights(opportunity: Opportunity): Highlight[] {
  const evidence = opportunity.evidence;
  const items: Highlight[] = [];
  const resonance = evidenceNumber(evidence, "resonance_strength");
  if (resonance !== null) {
    items.push({ label: "共振强度", value: formatPlainPercent(resonance, 1) });
  }
  const meanReturn = evidenceNumber(evidence, "mean_ret_5d");
  if (meanReturn !== null) {
    items.push({ label: "5 日均值", value: formatSignedPercent(meanReturn) });
  }
  const spreadZ = evidenceNumber(evidence, "spread_z");
  if (spreadZ !== null) {
    items.push({ label: "价差 z", value: formatNumber(spreadZ, 2) });
  }
  const correlation = evidenceNumber(evidence, "correlation");
  if (correlation !== null) {
    items.push({ label: "相关", value: formatNumber(correlation, 3) });
  }
  return items;
}

export function OpportunityCard({
  opportunity,
  selected,
  onSelect,
}: {
  opportunity: Opportunity;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className="text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <Card
        className={cn(
          "h-full transition-colors hover:border-foreground/25",
          selected && "border-foreground/40 bg-accent/40",
        )}
      >
        <CardHeader className="gap-3 pb-3">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle className="text-lg">
                {opportunity.primary_symbol ?? opportunity.primary_inst_id ?? "—"}
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                {kindLabels[opportunity.kind]} · {directionLabels[opportunity.direction]} ·{" "}
                {opportunity.horizon}
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">得分</p>
              <p className="text-lg font-semibold tabular-nums">
                {formatScore(opportunity.score)}
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <ul className="space-y-1.5">
            {opportunity.reasons.slice(0, 2).map((reason, index) => (
              <li
                key={`${index}-${reason}`}
                className="text-sm leading-5 text-muted-foreground"
              >
                {reason}
              </li>
            ))}
          </ul>
          {highlights(opportunity).length > 0 ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 border-t pt-3 text-xs">
              {highlights(opportunity).map((item) => (
                <div key={item.label} className="flex items-baseline justify-between gap-2">
                  <dt className="text-muted-foreground">{item.label}</dt>
                  <dd className="tabular-nums">{item.value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          <p className="text-xs text-muted-foreground">查看完整理由与证据 →</p>
        </CardContent>
      </Card>
    </button>
  );
}
