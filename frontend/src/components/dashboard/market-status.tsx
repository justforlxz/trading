/** 市场状态条：时段、截面时间、广度与扫描覆盖。数值全部来自 API。 */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import type { MarketSnapshot, OpportunityRun } from "../../lib/api";
import { formatTimestamp } from "../../pages/research/format";
import {
  formatDuration,
  formatPlainPercent,
  sessionLabels,
} from "./format";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="space-y-1">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold tabular-nums">{value}</p>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function MarketStatusPanel({
  snapshot,
  run,
}: {
  snapshot: MarketSnapshot;
  run: OpportunityRun | null;
}) {
  const counts = run?.counts ?? {};
  const breadth = snapshot.breadth;
  const universe = counts.universe ?? run?.universe_size ?? null;
  const covered = counts.snapshot ?? snapshot.count;
  const missing = counts.missing;
  const missingNotes: string[] = [];
  if (missing?.private_company.length) {
    missingNotes.push(`私募公司无行情：${missing.private_company.join("、")}`);
  }
  if (missing?.no_candles.length) {
    missingNotes.push(`无 K 线：${missing.no_candles.join("、")}`);
  }
  if (missing?.insufficient_bars.length) {
    missingNotes.push(`样本不足：${missing.insufficient_bars.join("、")}`);
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle>市场状态</CardTitle>
            <CardDescription>截面 {formatTimestamp(snapshot.as_of)}</CardDescription>
          </div>
          <span className="rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground">
            {sessionLabels[snapshot.session] ?? snapshot.session}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="广度"
            value={
              breadth
                ? `${breadth.up} 涨 / ${breadth.down} 跌 / ${breadth.flat} 平`
                : "—"
            }
            hint={breadth ? `上涨占比 ${formatPlainPercent(breadth.up_ratio, 1)}` : undefined}
          />
          <Stat
            label="截面覆盖"
            value={covered === null ? "—" : `${covered} / ${universe ?? "—"}`}
            hint="已落库标的 / universe"
          />
          <Stat label="聚类" value={counts.clusters === undefined ? "—" : `${counts.clusters} 簇`} />
          <Stat
            label="扫描耗时"
            value={formatDuration(counts.duration_ms)}
            hint={run ? `批次 #${run.id}` : undefined}
          />
        </div>
        {missingNotes.length > 0 ? (
          <p className="border-t pt-3 text-xs leading-5 text-muted-foreground">
            {missingNotes.join("；")}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
