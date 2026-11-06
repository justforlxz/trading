/** 单条机会详情：全部理由、可复算证据与成员明细；不做二次计算。 */

import type { OpportunityDetail } from "../../lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import { Button } from "../ui/button";
import {
  directionLabels,
  evidenceNumber,
  evidenceString,
  formatNumber,
  formatPlainPercent,
  formatScore,
  formatSignedPercent,
  kindLabels,
} from "./format";

type EvidenceEntry = { label: string; value: string };

function anomalyEntries(evidence: Record<string, unknown>): EvidenceEntry[] {
  const anomaly = evidence.anomaly;
  if (!anomaly || typeof anomaly !== "object") {
    return [];
  }
  const record = anomaly as Record<string, unknown>;
  const entries: EvidenceEntry[] = [];
  const window = record.window;
  if (typeof window === "number") entries.push({ label: "突变窗口", value: `${window} 根` });
  const baseline = record.baseline;
  if (typeof baseline === "number") {
    entries.push({ label: "基线相关", value: formatNumber(baseline, 3) });
  }
  const recent = record.recent;
  if (typeof recent === "number") {
    entries.push({ label: "近期相关", value: formatNumber(recent, 3) });
  }
  const delta = record.delta;
  if (typeof delta === "number") {
    entries.push({ label: "相关变化", value: formatNumber(delta, 3) });
  }
  if (record.flagged === true) entries.push({ label: "判定", value: "已标记为相关性突变" });
  return entries;
}

function evidenceEntries(evidence: Record<string, unknown>): EvidenceEntry[] {
  const entries: EvidenceEntry[] = [];
  const cluster = evidenceString(evidence, "cluster");
  if (cluster) entries.push({ label: "所属簇", value: cluster });
  const clusterSize = evidenceNumber(evidence, "cluster_size");
  if (clusterSize !== null) {
    entries.push({ label: "簇规模", value: `${Math.round(clusterSize)} 只` });
  }
  const resonance = evidenceNumber(evidence, "resonance_strength");
  if (resonance !== null) {
    entries.push({ label: "共振强度", value: formatPlainPercent(resonance, 1) });
  }
  const meanReturn = evidenceNumber(evidence, "mean_ret_5d");
  if (meanReturn !== null) {
    entries.push({ label: "簇内 5 日均值", value: formatSignedPercent(meanReturn) });
  }
  const leaderReturn = evidenceNumber(evidence, "leader_ret_5d");
  if (leaderReturn !== null) {
    entries.push({ label: "主导标的 5 日", value: formatSignedPercent(leaderReturn) });
  }
  const spreadZ = evidenceNumber(evidence, "spread_z");
  if (spreadZ !== null) entries.push({ label: "价差偏离 z", value: formatNumber(spreadZ, 2) });
  const correlation = evidenceNumber(evidence, "correlation");
  if (correlation !== null) {
    entries.push({ label: "相关系数", value: formatNumber(correlation, 3) });
  }
  const overlap = evidenceNumber(evidence, "overlap_bars");
  if (overlap !== null) {
    entries.push({ label: "共同样本", value: `${Math.round(overlap)} 根` });
  }
  const silhouette = evidenceNumber(evidence, "silhouette");
  if (silhouette !== null) {
    entries.push({ label: "轮廓系数", value: formatNumber(silhouette, 3) });
  }
  return [...entries, ...anomalyEntries(evidence)];
}

export function OpportunityDetailPanel({
  detail,
  loading,
  error,
  onClose,
}: {
  detail: OpportunityDetail | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}) {
  if (loading) {
    return (
      <Card>
        <CardContent className="py-10 text-sm text-muted-foreground">正在读取机会详情…</CardContent>
      </Card>
    );
  }
  if (error) {
    return (
      <Card>
        <CardContent className="py-10 text-sm text-destructive">{error}</CardContent>
      </Card>
    );
  }
  if (!detail) {
    return null;
  }

  const entries = evidenceEntries(detail.evidence);
  const longLeg = evidenceString(detail.evidence, "long_inst_id");
  const shortLeg = evidenceString(detail.evidence, "short_inst_id");

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="text-lg">
              {detail.primary_symbol ?? detail.primary_inst_id ?? "—"} · 机会详情
            </CardTitle>
            <CardDescription>
              {kindLabels[detail.kind]} · {directionLabels[detail.direction]} ·{" "}
              {detail.horizon} · 批次 #{detail.run_id}
            </CardDescription>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">
              得分 <span className="font-semibold tabular-nums">{formatScore(detail.score)}</span>
            </span>
            <Button variant="ghost" size="sm" onClick={onClose}>
              收起
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <section className="space-y-2">
          <h4 className="text-sm font-medium">为什么是它</h4>
          <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
            {detail.reasons.map((reason, index) => (
              <li key={`${index}-${reason}`}>{reason}</li>
            ))}
          </ol>
        </section>

        {longLeg || shortLeg ? (
          <section className="space-y-2">
            <h4 className="text-sm font-medium">配对腿</h4>
            <p className="text-sm text-muted-foreground">
              做多 {longLeg ?? "—"} / 做空 {shortLeg ?? "—"}
            </p>
          </section>
        ) : null}

        {entries.length > 0 ? (
          <section className="space-y-2">
            <h4 className="text-sm font-medium">关键证据</h4>
            <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
              {entries.map((entry) => (
                <div key={entry.label} className="flex items-baseline justify-between gap-3">
                  <dt className="text-muted-foreground">{entry.label}</dt>
                  <dd className="tabular-nums">{entry.value}</dd>
                </div>
              ))}
            </dl>
          </section>
        ) : null}

        {detail.members.length > 0 ? (
          <section className="space-y-2">
            <h4 className="text-sm font-medium">簇内成员</h4>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-4 font-medium">标的</th>
                    <th className="py-2 pr-4 font-medium">1 日</th>
                    <th className="py-2 pr-4 font-medium">5 日</th>
                    <th className="py-2 pr-4 font-medium">20 日</th>
                    <th className="py-2 pr-4 font-medium">簇内相关</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.members.map((member) => (
                    <tr key={member.instrument_id} className="border-b last:border-0">
                      <td className="py-2 pr-4">{member.symbol}</td>
                      <td className="py-2 pr-4 tabular-nums">
                        {formatSignedPercent(member.ret_1d)}
                      </td>
                      <td className="py-2 pr-4 tabular-nums">
                        {formatSignedPercent(member.ret_5d)}
                      </td>
                      <td className="py-2 pr-4 tabular-nums">
                        {formatSignedPercent(member.ret_20d)}
                      </td>
                      <td className="py-2 pr-4 tabular-nums">
                        {formatNumber(member.correlation, 3)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}

        <details className="space-y-2">
          <summary className="cursor-pointer text-sm font-medium">原始证据 JSON</summary>
          <pre className="mt-2 max-h-72 overflow-auto rounded-md border bg-muted/30 p-3 text-xs leading-5">
            {JSON.stringify(detail.evidence, null, 2)}
          </pre>
        </details>
      </CardContent>
    </Card>
  );
}
