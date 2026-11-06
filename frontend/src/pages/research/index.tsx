import { Loader2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PageHeading } from "../../components/layout/page-parts";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import * as api from "../../lib/api";
import type {
  CorrelationMethod,
  CreateTargetInput,
  JobRun,
  PriceBasis,
  RelationHistoryEntry,
  RelationsPayload,
  RelativeStrengthPayload,
  Target,
} from "../../lib/api";
import { CorrelationTable, SignificantChanges } from "./correlation-table";
import { formatTimestamp } from "./format";
import { RelationGraph } from "./relation-graph";
import { RelativeStrength } from "./relative-strength";
import { TargetPanel } from "./target-panel";

function describe(error: unknown): string {
  if (error instanceof api.ApiError) {
    return `${error.code}：${error.message}`;
  }
  return error instanceof Error ? error.message : "未知错误";
}

function jobNote(job: JobRun): string {
  const reason = typeof job.result?.reason === "string" ? job.result.reason : null;
  const detail = job.error ?? reason;
  switch (job.status) {
    case "ok":
      return `快照已生成（任务 #${job.id}）。`;
    case "skipped":
      return "相同参数已有快照，本次跳过，没有产生重复记录。";
    case "partial":
      return `任务 #${job.id} 未产生可用的边：${detail ?? "样本不足"}`;
    case "failed":
      return `任务 #${job.id} 失败：${detail ?? "未知错误"}`;
    default:
      return `任务 #${job.id} 仍在 ${job.status} 状态，稍后刷新查看。`;
  }
}

export default function ResearchPage() {
  const [targets, setTargets] = useState<Target[]>([]);
  const [targetsLoading, setTargetsLoading] = useState(true);
  const [targetsError, setTargetsError] = useState<string | null>(null);
  const [targetBusy, setTargetBusy] = useState(false);
  const [selectedTargetId, setSelectedTargetId] = useState<number | null>(null);

  const [relations, setRelations] = useState<RelationsPayload | null>(null);
  const [relationsLoading, setRelationsLoading] = useState(false);
  const [relationsError, setRelationsError] = useState<string | null>(null);
  const [history, setHistory] = useState<RelationHistoryEntry[]>([]);

  const [windowBars, setWindowBars] = useState(60);
  const [method, setMethod] = useState<CorrelationMethod>("pearson");
  const [priceBasis, setPriceBasis] = useState<PriceBasis>("okx_close");
  const [recomputeBusy, setRecomputeBusy] = useState(false);
  const [recomputeNote, setRecomputeNote] = useState<string | null>(null);

  const [selectedCounterparty, setSelectedCounterparty] = useState<string | null>(null);
  const [lookback, setLookback] = useState(60);
  const [relativeStrength, setRelativeStrength] = useState<RelativeStrengthPayload | null>(null);
  const [relativeStrengthLoading, setRelativeStrengthLoading] = useState(false);
  const [relativeStrengthError, setRelativeStrengthError] = useState<string | null>(null);

  const selectedTarget = useMemo(
    () => targets.find((target) => target.id === selectedTargetId) ?? null,
    [targets, selectedTargetId],
  );

  const loadTargets = useCallback(async () => {
    setTargetsLoading(true);
    setTargetsError(null);
    try {
      const payload = await api.listTargets();
      setTargets(payload.items);
      setSelectedTargetId((current) => {
        if (current !== null && payload.items.some((target) => target.id === current)) {
          return current;
        }
        return payload.items[0]?.id ?? null;
      });
    } catch (error) {
      setTargetsError(describe(error));
    } finally {
      setTargetsLoading(false);
    }
  }, []);

  const loadRelations = useCallback(async (targetId: number) => {
    setRelationsLoading(true);
    setRelationsError(null);
    try {
      const [payload, entries] = await Promise.all([
        api.getRelations(targetId),
        api.getRelationHistory(targetId, 10),
      ]);
      setRelations(payload);
      setHistory(entries);
    } catch (error) {
      setRelations(null);
      setHistory([]);
      setRelationsError(describe(error));
    } finally {
      setRelationsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTargets();
  }, [loadTargets]);

  useEffect(() => {
    if (selectedTargetId === null) {
      setRelations(null);
      setHistory([]);
      return;
    }
    void loadRelations(selectedTargetId);
  }, [loadRelations, selectedTargetId]);

  useEffect(() => {
    const edges = relations?.edges ?? [];
    setSelectedCounterparty((current) => {
      if (current !== null && edges.some((edge) => edge.counterparty_inst_id === current)) {
        return current;
      }
      return edges[0]?.counterparty_inst_id ?? null;
    });
  }, [relations]);

  useEffect(() => {
    if (selectedTargetId === null || selectedCounterparty === null) {
      setRelativeStrength(null);
      setRelativeStrengthError(null);
      setRelativeStrengthLoading(false);
      return;
    }
    let cancelled = false;
    setRelativeStrengthLoading(true);
    setRelativeStrengthError(null);
    api
      .getRelativeStrength(selectedTargetId, {
        counterparty: selectedCounterparty,
        lookback,
        priceBasis,
      })
      .then((payload) => {
        if (!cancelled) {
          setRelativeStrength(payload);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setRelativeStrength(null);
          setRelativeStrengthError(describe(error));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setRelativeStrengthLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [lookback, priceBasis, selectedCounterparty, selectedTargetId]);

  async function handleCreate(input: CreateTargetInput) {
    setTargetBusy(true);
    setTargetsError(null);
    try {
      const created = await api.createTarget(input);
      await loadTargets();
      setSelectedTargetId(created.id);
      setRecomputeNote(null);
    } catch (error) {
      setTargetsError(describe(error));
    } finally {
      setTargetBusy(false);
    }
  }

  async function handleDelete(target: Target) {
    setTargetBusy(true);
    setTargetsError(null);
    try {
      await api.deleteTarget(target.id);
      await loadTargets();
    } catch (error) {
      setTargetsError(describe(error));
    } finally {
      setTargetBusy(false);
    }
  }

  async function handleRecompute() {
    if (selectedTargetId === null) {
      return;
    }
    setRecomputeBusy(true);
    setRecomputeNote(null);
    setRelationsError(null);
    try {
      const accepted = await api.recomputeRelations(selectedTargetId, {
        window_bars: Math.max(3, windowBars),
        method,
        price_basis: priceBasis,
      });
      if (accepted.status === "skipped") {
        setRecomputeNote("相同参数已有快照，本次跳过，没有产生重复记录。");
      } else {
        setRecomputeNote(`任务 #${accepted.job_id} 已提交，等待计算结果…`);
        const job = await api.waitForJob(accepted.job_id);
        setRecomputeNote(jobNote(job));
      }
      await loadRelations(selectedTargetId);
    } catch (error) {
      setRelationsError(describe(error));
    } finally {
      setRecomputeBusy(false);
    }
  }

  const snapshot = relations?.snapshot ?? null;

  return (
    <>
      <PageHeading
        eyebrow="Research"
        title="研究"
        description="以目标股票为分析锚点查看动态相关性、关系网络与相对强弱。相关性只使用对齐后的真实收盘价序列，行情缺失时后端会明确标注，不做混用。关系网络只做分析展示，不承担策略编辑。"
      />

      <div className="grid items-start gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        <TargetPanel
          targets={targets}
          selectedId={selectedTargetId}
          loading={targetsLoading}
          busy={targetBusy}
          error={targetsError}
          onSelect={setSelectedTargetId}
          onCreate={handleCreate}
          onDelete={handleDelete}
        />

        <div className="min-w-0 space-y-6">
          {selectedTarget === null ? (
            <Card>
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground">
                  先在左侧添加一个目标股票，再计算它的关系快照。
                </p>
              </CardContent>
            </Card>
          ) : (
            <>
              <Card>
                <CardHeader>
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="space-y-1.5">
                      <CardTitle>{selectedTarget.symbol} 的关系网络</CardTitle>
                      <CardDescription>
                        {selectedTarget.exchange}
                        {selectedTarget.display_name ? ` · ${selectedTarget.display_name}` : ""}
                        {snapshot
                          ? ` · 截至 ${formatTimestamp(snapshot.as_of)}`
                          : " · 尚无快照"}
                      </CardDescription>
                    </div>
                    <div className="flex flex-wrap items-end gap-2">
                      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        窗口
                        <input
                          type="number"
                          min={3}
                          max={2000}
                          value={windowBars}
                          onChange={(event) => setWindowBars(Number(event.target.value))}
                          className="h-8 w-20 rounded-md border bg-background px-2 text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        />
                        根
                      </label>
                      <select
                        aria-label="相关性方法"
                        value={method}
                        onChange={(event) => setMethod(event.target.value as CorrelationMethod)}
                        className="h-8 rounded-md border bg-background px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <option value="pearson">pearson</option>
                        <option value="spearman">spearman</option>
                      </select>
                      <select
                        aria-label="价格口径"
                        value={priceBasis}
                        onChange={(event) => setPriceBasis(event.target.value as PriceBasis)}
                        className="h-8 rounded-md border bg-background px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <option value="okx_close">okx_close</option>
                        <option value="equity_close">equity_close</option>
                      </select>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => void handleRecompute()}
                        disabled={recomputeBusy}
                      >
                        {recomputeBusy ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <RefreshCw className="h-4 w-4" />
                        )}
                        重新计算
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  {recomputeNote ? (
                    <p className="rounded-md bg-muted/60 px-3 py-2 text-xs leading-5 text-muted-foreground">
                      {recomputeNote}
                    </p>
                  ) : null}
                  {relationsError ? (
                    <p className="text-sm text-destructive">{relationsError}</p>
                  ) : null}
                  {relationsLoading && !relations ? (
                    <p className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      读取关系快照…
                    </p>
                  ) : null}

                  {snapshot ? (
                    <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-lg bg-muted/40 p-3 text-xs sm:grid-cols-4">
                      <div>
                        <dt className="text-muted-foreground">方法</dt>
                        <dd className="font-mono">{snapshot.method}</dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">价格口径</dt>
                        <dd className="font-mono">{snapshot.price_basis}</dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">窗口 / 最大滞后</dt>
                        <dd className="font-mono">
                          {snapshot.window_bars} / {snapshot.lag_max}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">样本量</dt>
                        <dd className="font-mono">{snapshot.sample_size}</dd>
                      </div>
                    </dl>
                  ) : null}

                  {relations && relations.status === "undefined" && relations.edges.length === 0 ? (
                    <div className="rounded-lg border border-dashed p-4 text-sm leading-6 text-muted-foreground">
                      {relations.reason ?? "关系未定义。"}
                    </div>
                  ) : null}

                  {relations && relations.edges.length > 0 ? (
                    <RelationGraph
                      target={selectedTarget}
                      payload={relations}
                      onSelectCounterparty={setSelectedCounterparty}
                    />
                  ) : null}

                  {!relationsLoading && !relations && !relationsError ? (
                    <p className="text-sm text-muted-foreground">
                      还没有计算过关系快照，先点「重新计算」。
                    </p>
                  ) : null}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>相关性明细</CardTitle>
                  <CardDescription>
                    按 |系数| 降序排名；点选一行把它作为相对强弱的对手方。
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <CorrelationTable
                    edges={relations?.edges ?? []}
                    selectedCounterparty={selectedCounterparty}
                    onSelect={setSelectedCounterparty}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>显著变化</CardTitle>
                  <CardDescription>
                    与上一快照对比：系数变化超过阈值或符号翻转才列出。
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <SignificantChanges changes={relations?.significant_changes ?? []} />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>快照历史</CardTitle>
                  <CardDescription>最近 10 次计算，按时间倒序。</CardDescription>
                </CardHeader>
                <CardContent>
                  {history.length === 0 ? (
                    <p className="text-sm text-muted-foreground">还没有快照。</p>
                  ) : (
                    <ul className="divide-y">
                      {history.map((entry) => (
                        <li
                          key={entry.id}
                          className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm"
                        >
                          <span className="text-muted-foreground">
                            {formatTimestamp(entry.as_of)}
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">
                            {entry.method} · {entry.price_basis} · 窗口 {entry.window_bars}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {entry.edge_count} 条边 · {entry.significant_changes.length} 项显著变化
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>

              <RelativeStrength
                payload={relativeStrength}
                loading={relativeStrengthLoading}
                error={relativeStrengthError}
                counterparty={selectedCounterparty}
                lookback={lookback}
                onLookbackChange={setLookback}
              />
            </>
          )}
        </div>
      </div>
    </>
  );
}
