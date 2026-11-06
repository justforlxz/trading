/** 市场驾驶舱（P1-13）：市场状态、按分数排序的机会卡片与单条证据下钻。 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../lib/api";
import { PageHeading } from "../components/layout/page-parts";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { ClusterPanel } from "../components/dashboard/cluster-panel";
import { MarketStatusPanel } from "../components/dashboard/market-status";
import { OpportunityCard } from "../components/dashboard/opportunity-card";
import { OpportunityDetailPanel } from "../components/dashboard/opportunity-detail";
import { formatTimestamp } from "./research/format";

function describe(error: unknown): string {
  if (error instanceof api.ApiError) {
    return `${error.code}：${error.message}`;
  }
  return error instanceof Error ? error.message : "请求失败";
}

function hasScanResults(run: api.OpportunityRun | null): boolean {
  return run !== null && (run.status === "ok" || run.status === "partial");
}

export function DashboardPage() {
  const [snapshot, setSnapshot] = useState<api.MarketSnapshot | null>(null);
  const [run, setRun] = useState<api.OpportunityRun | null>(null);
  const [opportunities, setOpportunities] = useState<api.Opportunity[]>([]);
  const [clusters, setClusters] = useState<api.AssetCluster[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [scanning, setScanning] = useState(false);
  const [scanNote, setScanNote] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<api.OpportunityDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [market, runs] = await Promise.all([
        api.getMarketSnapshot(),
        api.listOpportunityRuns({ limit: 1 }),
      ]);
      setSnapshot(market);
      const latest = runs.items[0] ?? null;
      setRun(latest);
      if (latest && hasScanResults(latest)) {
        const [list, clusterList] = await Promise.all([
          api.listOpportunities({ run_id: latest.id, limit: 50 }),
          api.listClusters(latest.id),
        ]);
        setOpportunities(list.items);
        setClusters(clusterList.items);
      } else {
        setOpportunities([]);
        setClusters([]);
      }
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runScan = useCallback(async () => {
    setScanning(true);
    setScanNote(null);
    try {
      const accepted = await api.scanOpportunities({});
      if (accepted.status === "skipped") {
        setScanNote("同一截面已有批次，直接读取现有结果。");
      }
      const job = await api.waitForJob(accepted.job_id, { attempts: 150, intervalMs: 2000 });
      if (job.status === "ok" || job.status === "partial") {
        setScanNote(`扫描${job.status === "ok" ? "完成" : "部分完成"}（任务 #${job.id}）。`);
      } else {
        setScanNote(job.error ?? `扫描未完成：${job.status}`);
      }
      await load();
    } catch (caught) {
      setScanNote(describe(caught));
    } finally {
      setScanning(false);
    }
  }, [load]);

  const openDetail = useCallback(async (opportunityId: number) => {
    setSelectedId(opportunityId);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      setDetail(await api.getOpportunity(opportunityId));
    } catch (caught) {
      setDetailError(describe(caught));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const closeDetail = useCallback(() => {
    setSelectedId(null);
    setDetail(null);
    setDetailError(null);
  }, []);

  const hasSnapshot = snapshot !== null && snapshot.as_of !== null;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageHeading
          eyebrow="Overview"
          title="市场驾驶舱"
          description="全市场机会按得分排序；点开任意机会可以看到它为什么被选中，以及可复算的相关、共振与偏离数值。"
        />
        <div className="flex flex-col items-end gap-2">
          <Button onClick={() => void runScan()} disabled={scanning}>
            {scanning ? "扫描中…" : "运行全市场扫描"}
          </Button>
          {scanNote ? (
            <p className="max-w-xs text-right text-xs text-muted-foreground">{scanNote}</p>
          ) : null}
        </div>
      </div>

      {error ? (
        <Card>
          <CardHeader>
            <CardTitle>暂时读不到驾驶舱数据</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              重试
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {loading && !snapshot ? (
        <Card>
          <CardContent className="py-10 text-sm text-muted-foreground">
            正在读取最新截面…
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && !hasSnapshot ? (
        <Card>
          <CardHeader>
            <CardTitle>尚未产生扫描结果</CardTitle>
            <CardDescription>
              全市场扫描需要候选标的的已确认日线。请先回填行情，再运行扫描；本页不会展示任何占位数值。
            </CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      {hasSnapshot ? <MarketStatusPanel snapshot={snapshot} run={run} /> : null}

      {hasSnapshot ? (
        <section className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-lg font-semibold tracking-tight">机会</h2>
            <p className="text-xs text-muted-foreground">
              {opportunities.length} 条 · 截面 {formatTimestamp(snapshot.as_of)}
            </p>
          </div>
          {opportunities.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-sm text-muted-foreground">
                该批次没有满足阈值的机会；可以放宽扫描参数后重跑。
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {opportunities.map((opportunity) => (
                <OpportunityCard
                  key={opportunity.id}
                  opportunity={opportunity}
                  selected={selectedId === opportunity.id}
                  onSelect={() => void openDetail(opportunity.id)}
                />
              ))}
            </div>
          )}
        </section>
      ) : null}

      {selectedId !== null ? (
        <OpportunityDetailPanel
          detail={detail}
          loading={detailLoading}
          error={detailError}
          onClose={closeDetail}
        />
      ) : null}

      {hasSnapshot ? <ClusterPanel clusters={clusters} /> : null}
    </div>
  );
}

export default DashboardPage;
