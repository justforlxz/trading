import { useEffect, useState } from "react";

import { RelationshipNetwork } from "../components/graph/relationship-network";
import { PageHeading } from "../components/layout/page-parts";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { fetchRelationGraph, type CandleBar, type RelationGraphResponse } from "../lib/api";

/** 关系网络看的是较长周期的关系，分钟级只留两个常用档。 */
const BAR_OPTIONS: CandleBar[] = ["1h", "4h", "1d"];
const WINDOW_OPTIONS = [20, 60, 120];
const THRESHOLD_OPTIONS = [0.3, 0.5, 0.7];

const DEFAULT_BAR: CandleBar = "1d";
const DEFAULT_WINDOW = 60;
const DEFAULT_THRESHOLD = 0.5;

/**
 * 关系网络页：把自选标的之间的相关性画成网络，并列出网络指标。
 *
 * 只做分析展示：点击节点只高亮邻居，不提供策略编辑入口，也不写任何数据。
 */
export default function RelationsPage() {
  const [bar, setBar] = useState<CandleBar>(DEFAULT_BAR);
  const [window, setWindow] = useState(DEFAULT_WINDOW);
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD);
  const [graph, setGraph] = useState<RelationGraphResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setGraph(null);
    setError(null);
    fetchRelationGraph(bar, window, threshold)
      .then((value) => {
        if (active) setGraph(value);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "关系网络加载失败");
      });
    return () => {
      active = false;
    };
  }, [bar, window, threshold]);

  return (
    <>
      <PageHeading
        eyebrow="Relations"
        title="关系网络"
        description="节点是自选里跟踪的标的，边是两个标的在该周期、该窗口上的相关系数；社区由同向关系给出。点击节点只高亮它的邻居。"
      />

      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <div className="space-y-1.5">
              <CardTitle>网络</CardTitle>
              <CardDescription>
                阈值以下的边不画；负相关的边画虚线。全市场扫描不属于本页范围。
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <ControlGroup
                label="周期"
                options={BAR_OPTIONS.map((option) => ({ value: option, label: option }))}
                current={bar}
                onSelect={setBar}
              />
              <ControlGroup
                label="窗口"
                options={WINDOW_OPTIONS.map((option) => ({
                  value: option,
                  label: `${option} 根`,
                }))}
                current={window}
                onSelect={setWindow}
              />
              <ControlGroup
                label="|相关系数| 下限"
                options={THRESHOLD_OPTIONS.map((option) => ({
                  value: option,
                  label: option.toFixed(1),
                }))}
                current={threshold}
                onSelect={setThreshold}
              />
            </div>

            {error ? (
              <p className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            ) : null}

            {!error && !graph ? (
              <p className="py-16 text-center text-sm text-muted-foreground">加载中…</p>
            ) : null}

            {graph ? <RelationshipNetwork graph={graph} /> : null}

            {graph && graph.nodes.length > 0 ? (
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span className="rounded-full border px-2 py-0.5">
                  as_of {graph.as_of}
                </span>
                <span className="rounded-full border px-2 py-0.5">周期 {graph.bar}</span>
                <span className="rounded-full border px-2 py-0.5">窗口 {graph.window}</span>
                <span className="rounded-full border px-2 py-0.5">
                  阈值 {graph.min_abs_corr}
                </span>
                <span className="rounded-full border px-2 py-0.5">
                  平均连通度 {graph.average_degree}
                </span>
              </div>
            ) : null}
          </CardContent>
        </Card>

        {graph && graph.nodes.length > 0 ? (
          <Card>
            <CardHeader>
              <div className="space-y-1.5">
                <CardTitle>网络指标</CardTitle>
                <CardDescription>
                  度数数的是画出来的边；中心性 = 度数 / (节点数 - 1)。
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="pb-2 font-medium">标的</th>
                    <th className="pb-2 font-medium">社区</th>
                    <th className="pb-2 text-right font-medium">度数</th>
                    <th className="pb-2 text-right font-medium">度中心性</th>
                  </tr>
                </thead>
                <tbody>
                  {graph.nodes.map((node) => (
                    <tr key={node.product_key} className="border-t">
                      <td className="py-2 font-medium">{node.product_key}</td>
                      <td className="py-2 text-muted-foreground">社区 {node.community_id}</td>
                      <td className="py-2 text-right tabular-nums">{node.degree}</td>
                      <td className="py-2 text-right tabular-nums">{node.centrality}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        ) : null}
      </div>
    </>
  );
}

function ControlGroup<T extends string | number>({
  label,
  options,
  current,
  onSelect,
}: {
  label: string;
  options: Array<{ value: T; label: string }>;
  current: T;
  onSelect: (value: T) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="flex flex-wrap gap-1" role="group" aria-label={label}>
        {options.map((option) => (
          <Button
            key={String(option.value)}
            type="button"
            size="sm"
            variant={option.value === current ? "default" : "outline"}
            aria-pressed={option.value === current}
            onClick={() => onSelect(option.value)}
          >
            {option.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
