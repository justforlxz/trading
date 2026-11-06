import { Loader2, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

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
import type { Strategy, StrategyStatus } from "../../lib/api";
import { cn } from "../../lib/utils";

const STATUS_ORDER: StrategyStatus[] = [
  "draft",
  "pending_approval",
  "approved",
  "rejected",
  "archived",
];

const STATUS_LABELS: Record<StrategyStatus, string> = {
  draft: "草稿",
  pending_approval: "待审批",
  approved: "已批准",
  rejected: "已拒绝",
  archived: "已归档",
};

const STATUS_TONES: Record<StrategyStatus, string> = {
  draft: "border-border bg-muted text-muted-foreground",
  pending_approval: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  approved: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  rejected: "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400",
  archived: "border-border bg-muted text-muted-foreground",
};

function describe(error: unknown): string {
  if (error instanceof api.ApiError) {
    return `${error.code}：${error.message}`;
  }
  return error instanceof Error ? error.message : "未知错误";
}

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatWeight(value: string): string {
  const weight = Number(value);
  if (Number.isNaN(weight)) return value;
  return weight.toFixed(4);
}

function StatusBadge({ status }: { status: StrategyStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs",
        STATUS_TONES[status],
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

export default function StrategiesPage() {
  const [statusFilter, setStatusFilter] = useState<StrategyStatus | null>(null);
  const [items, setItems] = useState<Strategy[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Strategy | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");

  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setListLoading(true);
    const params: { status?: StrategyStatus } = {};
    if (statusFilter) params.status = statusFilter;
    api
      .listStrategies(params)
      .then((data) => {
        if (cancelled) return;
        setItems(data.items);
        setListError(null);
        setSelectedId((previous) => {
          if (previous !== null && data.items.some((item) => item.id === previous)) {
            return previous;
          }
          return data.items[0]?.id ?? null;
        });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setItems([]);
        setListError(describe(error));
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [statusFilter, reloadToken]);

  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    api
      .getStrategy(selectedId)
      .then((strategy) => {
        if (cancelled) return;
        setDetail(strategy);
        setDetailError(null);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setDetail(null);
        setDetailError(describe(error));
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, reloadToken]);

  async function run(action: () => Promise<unknown>): Promise<boolean> {
    setBusy(true);
    setActionError(null);
    try {
      await action();
      setReloadToken((token) => token + 1);
      return true;
    } catch (error) {
      setActionError(describe(error));
      return false;
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = detail?.status === "draft";
  const canDecide = detail?.status === "pending_approval";
  const canArchive = detail?.status === "approved" || detail?.status === "rejected";
  const reviewerReady = reviewer.trim().length > 0;

  return (
    <>
      <PageHeading
        eyebrow="Strategies"
        title="策略"
        description="由目标股票关系或全市场机会生成的组合策略草案。组合成员、交易方向与目标权重的调整必须经过人工批准，批准后内容只读。"
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase tracking-[0.08em] text-muted-foreground">状态筛选</span>
        <Button
          size="sm"
          variant={statusFilter === null ? "default" : "outline"}
          onClick={() => setStatusFilter(null)}
        >
          全部
        </Button>
        {STATUS_ORDER.map((status) => (
          <Button
            key={status}
            size="sm"
            variant={statusFilter === status ? "default" : "outline"}
            onClick={() => setStatusFilter(status)}
          >
            {STATUS_LABELS[status]}
          </Button>
        ))}
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto"
          disabled={listLoading}
          onClick={() => setReloadToken((token) => token + 1)}
        >
          {listLoading ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <RefreshCw className="size-3.5" />
          )}
          刷新
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(280px,360px)_1fr]">
        <Card className="self-start">
          <CardHeader>
            <CardTitle>策略列表</CardTitle>
            <CardDescription>
              {listLoading ? "加载中…" : `共 ${items.length} 条`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {listError && (
              <p className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400">
                {listError}
              </p>
            )}
            {!listError && !listLoading && items.length === 0 && (
              <p className="text-sm text-muted-foreground">
                当前筛选下没有策略。策略由机会扫描或目标股票分析生成后写入。
              </p>
            )}
            <ul className="space-y-2">
              {items.map((item) => {
                const active = item.id === selectedId;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(item.id)}
                      className={cn(
                        "w-full rounded-lg border px-3 py-2 text-left transition-colors hover:bg-accent/60",
                        active ? "border-foreground/30 bg-accent/80" : "border-border/60",
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-medium">{item.name}</span>
                        <StatusBadge status={item.status} />
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                        <span className="font-mono">#{item.id}</span>
                        <span>{item.kind === "directional" ? "方向性" : "相对价值"}</span>
                        <span>{item.legs.length} 腿</span>
                        <span>审批人 {item.reviewer ?? "—"}</span>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        更新于 {formatTimestamp(item.updated_at)}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>

        <div className="space-y-6">
          {detailError && (
            <p className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400">
              {detailError}
            </p>
          )}

          {detailLoading && !detail && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              正在加载策略详情…
            </p>
          )}

          {!detailError && !detail && !detailLoading && (
            <p className="text-sm text-muted-foreground">从左侧选择一条策略查看详情。</p>
          )}

          {detail && (
            <Card>
              <CardHeader>
                <div className="flex flex-wrap items-center gap-3">
                  <CardTitle>{detail.name}</CardTitle>
                  <StatusBadge status={detail.status} />
                  <span className="text-xs text-muted-foreground">版本 v{detail.version}</span>
                </div>
                <CardDescription>
                  #{detail.id} · {detail.kind === "directional" ? "方向性策略" : "相对价值策略"} ·
                  来源{" "}
                  {detail.source?.type === "opportunity"
                    ? `机会 #${String(detail.source.opportunity_id ?? "")}`
                    : detail.source?.type === "target"
                      ? `目标 #${String(detail.source.target_id ?? "")}`
                      : "—"}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-muted-foreground">内容指纹</dt>
                    <dd className="truncate font-mono text-xs" title={detail.content_hash}>
                      {detail.content_hash}
                    </dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-muted-foreground">审批人</dt>
                    <dd>{detail.reviewer ?? "—"}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-muted-foreground">创建时间</dt>
                    <dd>{formatTimestamp(detail.created_at)}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-muted-foreground">批准时间</dt>
                    <dd>{formatTimestamp(detail.approved_at)}</dd>
                  </div>
                </dl>

                <div className="space-y-3 rounded-lg border border-border/60 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      disabled={busy || !canSubmit}
                      onClick={() => {
                        const id = detail.id;
                        void run(() => api.submitStrategy(id));
                      }}
                    >
                      提交审批
                    </Button>
                    <Button
                      size="sm"
                      disabled={busy || !canDecide || !reviewerReady}
                      onClick={() => {
                        const id = detail.id;
                        const body = note.trim();
                        void run(async () => {
                          await api.approveStrategy(id, reviewer.trim(), body || undefined);
                          setNote("");
                        });
                      }}
                    >
                      批准
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy || !canDecide || !reviewerReady || note.trim().length === 0}
                      onClick={() => {
                        const id = detail.id;
                        const body = note.trim();
                        void run(async () => {
                          await api.rejectStrategy(id, reviewer.trim(), body);
                          setNote("");
                        });
                      }}
                    >
                      驳回
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy || !canArchive}
                      onClick={() => {
                        const id = detail.id;
                        void run(() => api.archiveStrategy(id));
                      }}
                    >
                      归档
                    </Button>
                    {busy && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <label className="text-sm">
                      <span className="mb-1 block text-muted-foreground">审批人</span>
                      <input
                        value={reviewer}
                        onChange={(event) => setReviewer(event.target.value)}
                        placeholder="审批人姓名"
                        className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      />
                    </label>
                    <label className="text-sm">
                      <span className="mb-1 block text-muted-foreground">审批意见</span>
                      <input
                        value={note}
                        onChange={(event) => setNote(event.target.value)}
                        placeholder="批准可留空，驳回必填"
                        className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      />
                    </label>
                  </div>
                  {actionError && (
                    <p className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400">
                      {actionError}
                    </p>
                  )}
                  {detail.status === "pending_approval" && !reviewerReady && (
                    <p className="text-xs text-muted-foreground">
                      填写审批人后才能批准或驳回。
                    </p>
                  )}
                </div>

                <section>
                  <h3 className="mb-2 text-sm font-medium">组合成员</h3>
                  {detail.legs.length === 0 ? (
                    <p className="text-sm text-muted-foreground">该策略没有成员腿。</p>
                  ) : (
                    <div className="-mx-1 overflow-x-auto px-1">
                      <table className="w-full min-w-[720px] border-collapse text-sm">
                        <thead>
                          <tr className="border-b text-left text-xs uppercase tracking-[0.08em] text-muted-foreground">
                            <th className="py-2 pr-4 font-medium">排名</th>
                            <th className="py-2 pr-4 font-medium">标的</th>
                            <th className="py-2 pr-4 font-medium">方向</th>
                            <th className="py-2 pr-4 font-medium">权重</th>
                            <th className="py-2 font-medium">量化依据</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detail.legs.map((leg) => (
                            <tr key={leg.id} className="border-b border-border/60 last:border-0">
                              <td className="py-2 pr-4 font-mono text-muted-foreground">
                                #{leg.rank}
                              </td>
                              <td className="py-2 pr-4">
                                <span className="font-medium">
                                  {leg.symbol ?? leg.inst_id}
                                </span>
                                {leg.symbol ? (
                                  <span className="block font-mono text-xs text-muted-foreground">
                                    {leg.inst_id}
                                  </span>
                                ) : null}
                              </td>
                              <td
                                className={cn(
                                  "py-2 pr-4",
                                  leg.side === "long"
                                    ? "text-emerald-700 dark:text-emerald-400"
                                    : "text-red-700 dark:text-red-400",
                                )}
                              >
                                {leg.side === "long" ? "多" : "空"}
                              </td>
                              <td className="py-2 pr-4 font-mono">
                                {formatWeight(leg.weight)}
                              </td>
                              <td className="py-2 text-xs text-muted-foreground">
                                {leg.rationale}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {detail.exclusions.length > 0 && (
                    <div className="mt-3 rounded-md border border-border/60 px-3 py-2 text-xs text-muted-foreground">
                      <p className="mb-1 font-medium text-foreground">已排除标的</p>
                      <ul className="space-y-0.5">
                        {detail.exclusions.map((exclusion) => (
                          <li key={`${exclusion.instrument_id}-${exclusion.reason}`}>
                            <span className="font-mono">{exclusion.inst_id}</span>：
                            {exclusion.reason}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </section>

                <section>
                  <h3 className="mb-2 text-sm font-medium">状态时间线</h3>
                  {(detail.transitions ?? []).length === 0 ? (
                    <p className="text-sm text-muted-foreground">尚无状态变更。</p>
                  ) : (
                    <ol className="space-y-2">
                      {(detail.transitions ?? []).map((transition) => (
                        <li
                          key={transition.id}
                          className="rounded-md border border-border/60 px-3 py-2 text-sm"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <StatusBadge status={transition.from_status} />
                            <span className="text-muted-foreground">→</span>
                            <StatusBadge status={transition.to_status} />
                            <span className="ml-auto text-xs text-muted-foreground">
                              {formatTimestamp(transition.at)}
                            </span>
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            操作人 {transition.actor}
                            {transition.reason ? ` · ${transition.reason}` : ""}
                            {transition.request_id ? ` · 请求 ${transition.request_id}` : ""}
                          </div>
                        </li>
                      ))}
                    </ol>
                  )}
                </section>

                <section>
                  <h3 className="mb-2 text-sm font-medium">审批记录</h3>
                  {(detail.approvals ?? []).length === 0 ? (
                    <p className="text-sm text-muted-foreground">尚无审批记录。</p>
                  ) : (
                    <ul className="space-y-2">
                      {(detail.approvals ?? []).map((approval) => (
                        <li
                          key={approval.id}
                          className="rounded-md border border-border/60 px-3 py-2 text-sm"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span
                              className={cn(
                                "inline-flex items-center rounded-full border px-2 py-0.5 text-xs",
                                approval.decision === "approved"
                                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                                  : "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400",
                              )}
                            >
                              {approval.decision === "approved" ? "批准" : "驳回"}
                            </span>
                            <span>{approval.reviewer}</span>
                            <span className="ml-auto text-xs text-muted-foreground">
                              {formatTimestamp(approval.decided_at)}
                            </span>
                          </div>
                          <div className="mt-1 truncate font-mono text-xs text-muted-foreground">
                            内容指纹 {approval.content_hash}
                          </div>
                          {approval.note && (
                            <div className="mt-1 text-xs text-muted-foreground">
                              {approval.note}
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
