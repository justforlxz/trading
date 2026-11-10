import { useEffect, useState } from "react";

import { PageHeading, PendingPanel } from "../components/layout/page-parts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { fetchHealth, type Health } from "../lib/api";

const PLANNED = [
  "账户与组合总览",
  "市场时段与行情覆盖状态",
  "持仓与当日盈亏",
  "风险敞口与限额使用率",
];

export default function OverviewPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchHealth()
      .then((value) => {
        if (active) setHealth(value);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "后端不可达");
      });
    return () => {
      active = false;
    };
  }, []);

  const badge = health ? "在线" : error ? "离线" : "检查中";

  return (
    <>
      <PageHeading
        eyebrow="Overview"
        title="概览"
        description="市场驾驶舱。骨架阶段只验证前后端连通，业务面板与真实数据随对应节点接入。"
      />

      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-4">
              <CardTitle>后端连接</CardTitle>
              <span className="shrink-0 rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground">
                {badge}
              </span>
            </div>
            <CardDescription>
              通过 <code className="font-mono text-xs">GET /api/health</code> 确认后端进程存活；
              不探测交易所与行情源。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-4 text-sm sm:grid-cols-3">
              <div className="grid gap-1">
                <dt className="text-muted-foreground">状态</dt>
                <dd className="font-mono text-xs">{health?.status ?? "—"}</dd>
              </div>
              <div className="grid gap-1">
                <dt className="text-muted-foreground">版本</dt>
                <dd className="font-mono text-xs">{health?.version ?? "—"}</dd>
              </div>
              <div className="grid gap-1">
                <dt className="text-muted-foreground">环境</dt>
                <dd className="font-mono text-xs">{health?.env ?? "—"}</dd>
              </div>
            </dl>
            {error ? (
              <p className="mt-4 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            ) : null}
          </CardContent>
        </Card>

        <PendingPanel stage="后续节点" title="驾驶舱面板" items={PLANNED} />
      </div>
    </>
  );
}
