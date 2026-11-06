/** 资产簇概览：标签、规模、轮廓系数与成员（成员相关度来自后端）。 */

import type { AssetCluster } from "../../lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import { formatDecimal } from "../../pages/research/format";

export function ClusterPanel({ clusters }: { clusters: AssetCluster[] }) {
  if (clusters.length === 0) {
    return null;
  }
  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-tight">资产簇</h2>
        <p className="text-xs text-muted-foreground">按簇内平均相关度聚合，仅用于分析展示</p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {clusters.map((cluster) => (
          <Card key={cluster.id}>
            <CardHeader className="gap-1 pb-3">
              <div className="flex items-baseline justify-between gap-3">
                <CardTitle className="text-base">{cluster.label}</CardTitle>
                <span className="text-xs text-muted-foreground">
                  {cluster.size} 只 · {cluster.method}
                </span>
              </div>
              <CardDescription>
                轮廓系数 {formatDecimal(cluster.silhouette, 3)}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-wrap gap-2">
                {cluster.members.map((member) => (
                  <li
                    key={member.instrument_id}
                    className="rounded-full border px-2.5 py-1 text-xs"
                  >
                    {member.symbol}
                    <span className="ml-1.5 tabular-nums text-muted-foreground">
                      {formatDecimal(member.weight, 2)}
                    </span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
