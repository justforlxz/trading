import { useState } from "react";

import type { RelationGraphResponse } from "../../lib/api";
import {
  GRAPH_HEIGHT,
  GRAPH_WIDTH,
  NODE_RADIUS,
  layoutGraph,
  neighborsOf,
} from "../../lib/graph-layout";
import { cn } from "../../lib/utils";

/**
 * 关系网络图。
 *
 * 手写 SVG，不引入图表库，也不做力导向模拟：布局由 `lib/graph-layout` 的纯函数给出，
 * 因此同一份数据每次画出的位置完全相同。
 *
 * 交互只有一种——点击节点高亮它的邻居（以及相连的边），再点一次或点空白处取消。
 * 这是分析展示，不是策略编辑入口：不弹面板，也不写任何数据。
 */
export type RelationshipNetworkProps = {
  graph: RelationGraphResponse;
  className?: string;
};

/**
 * 社区配色：数量超过调色板时循环使用，颜色只用来区分分组，不承载业务含义。
 *
 * 两个类名都写成完整字面量（不拼接）：Tailwind 只扫描源码里出现过的类名，
 * 拼出来的 `bg-` 不会被生成。
 */
const COMMUNITY_COLOURS = [
  { fill: "fill-sky-500", dot: "bg-sky-500" },
  { fill: "fill-emerald-500", dot: "bg-emerald-500" },
  { fill: "fill-amber-500", dot: "bg-amber-500" },
  { fill: "fill-violet-500", dot: "bg-violet-500" },
  { fill: "fill-rose-500", dot: "bg-rose-500" },
  { fill: "fill-teal-500", dot: "bg-teal-500" },
  { fill: "fill-indigo-500", dot: "bg-indigo-500" },
  { fill: "fill-orange-500", dot: "bg-orange-500" },
] as const;

/** 负相关画虚线：正负是关系方向，不能只靠颜色区分。 */
const NEGATIVE_DASH = "4 4";

export function RelationshipNetwork({ graph, className }: RelationshipNetworkProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const layout = layoutGraph(graph.nodes, graph.edges);
  const active = layout.nodes.some((row) => row.productKey === selected) ? selected : null;
  const neighbours = active === null ? [] : neighborsOf(active, graph.edges);
  const highlighted = new Set(active === null ? [] : [active, ...neighbours]);
  const colourOf = (communityId: number) =>
    COMMUNITY_COLOURS[communityId % COMMUNITY_COLOURS.length];

  if (layout.nodes.length === 0) {
    return (
      <p className={cn("py-16 text-center text-sm text-muted-foreground", className)}>
        自选里还没有标的，关系网络需要至少两个被跟踪的标的。
      </p>
    );
  }

  return (
    <div className={cn("space-y-3", className)}>
      <svg
        viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`}
        className="w-full select-none"
        role="img"
        aria-label={`关系网络：${layout.nodes.length} 个标的，${layout.edges.length} 条边`}
        onClick={() => setSelected(null)}
      >
        <title>
          关系网络：{layout.nodes.length} 个标的，{layout.edges.length} 条边，
          {layout.communities.length} 个社区
        </title>

        {layout.edges.map((row) => {
          const dimmed = active !== null && !edgeTouches(row, active);
          return (
            <line
              key={`${row.productKeyA}-${row.productKeyB}`}
              x1={row.x1}
              y1={row.y1}
              x2={row.x2}
              y2={row.y2}
              strokeWidth={0.8 + Math.abs(row.coefficient) * 2.4}
              strokeDasharray={row.coefficient < 0 ? NEGATIVE_DASH : undefined}
              className={cn(
                row.coefficient < 0 ? "stroke-rose-400" : "stroke-sky-400",
                dimmed ? "opacity-10" : "opacity-70",
              )}
            >
              <title>
                {row.productKeyA} — {row.productKeyB}：{row.coefficient}
              </title>
            </line>
          );
        })}

        {layout.nodes.map((row) => {
          const dimmed = active !== null && !highlighted.has(row.productKey);
          const isActive = row.productKey === active;
          return (
            <g
              key={row.productKey}
              role="button"
              tabIndex={0}
              aria-pressed={isActive}
              aria-label={`${row.productKey}：${row.degree} 条关系，中心性 ${row.centrality}`}
              className={cn(
                "cursor-pointer focus-visible:outline-none",
                dimmed ? "opacity-25" : "opacity-100",
              )}
              onClick={(event) => {
                event.stopPropagation();
                setSelected(isActive ? null : row.productKey);
              }}
              onKeyDown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                setSelected(isActive ? null : row.productKey);
              }}
            >
              <circle
                cx={row.x}
                cy={row.y}
                r={NODE_RADIUS}
                strokeWidth={isActive ? 3 : 1.5}
                className={cn(colourOf(row.communityId).fill, "stroke-background")}
              />
              <text
                x={row.x}
                y={row.y + NODE_RADIUS + 13}
                textAnchor="middle"
                className="fill-foreground text-[11px] font-medium"
              >
                {row.productKey}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {layout.communities.map((community) => (
            <span key={community.communityId} className="inline-flex items-center gap-2">
              <span
                className={cn("h-2 w-2 rounded-full", colourOf(community.communityId).dot)}
                aria-hidden="true"
              />
              社区 {community.communityId} · {community.productKeys.join("、")}
            </span>
          ))}
        </div>
        <span>
          {active === null
            ? "点击节点查看它的邻居"
            : `${active} · ${neighbours.length} 个邻居 · 再点一次取消`}
        </span>
      </div>
    </div>
  );
}

function edgeTouches(
  edge: { productKeyA: string; productKeyB: string },
  key: string,
): boolean {
  return edge.productKeyA === key || edge.productKeyB === key;
}
