import type { EChartsOption } from "echarts";
import { useCallback, useMemo, useState } from "react";

import type { RelationEdge, RelationsPayload, Target } from "../../lib/api";
import { Chart, useChartTheme, type ChartClickParams } from "./chart";
import { formatDecimal, formatPValue, lagLabel } from "./format";

type RelationGraphProps = {
  target: Target;
  payload: RelationsPayload;
  onSelectCounterparty: (instId: string) => void;
};

type EdgeDatum = {
  edgeIndex: number;
  counterpartySymbol: string;
  coefficient: number;
  coefficientText: string;
  lagText: string;
  stabilityText: string;
  pValueText: string;
};

function edgeDatum(edge: RelationEdge, index: number): EdgeDatum {
  return {
    edgeIndex: index,
    counterpartySymbol: edge.counterparty.symbol ?? edge.counterparty_inst_id,
    coefficient: Number(edge.coefficient),
    coefficientText: formatDecimal(edge.coefficient),
    lagText: lagLabel(edge.best_lag),
    stabilityText: formatDecimal(edge.stability, 3),
    pValueText: formatPValue(edge.p_value),
  };
}

/**
 * 关系网络图：只读分析展示。
 *
 * 只启用缩放/平移（`roam`），节点不可拖动，没有任何增删边、
 * 权重或方向编辑入口。连线颜色表示系数符号，粗细表示 |系数|，
 * 箭头指向「跟随」的一方（`best_lag > 0` 表示对手方领先目标）。
 */
export function RelationGraph({ target, payload, onSelectCounterparty }: RelationGraphProps) {
  const theme = useChartTheme();
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const targetNodeId = `target-${target.id}`;

  const option = useMemo<EChartsOption>(() => {
    const nodes = [
      {
        id: targetNodeId,
        name: target.symbol,
        category: 0,
        symbolSize: 56,
        itemStyle: { color: theme.strongText },
        label: { position: "bottom", distance: 8, fontWeight: "bold" },
      },
      ...payload.edges.map((edge) => ({
        id: edge.counterparty_inst_id,
        name: edge.counterparty.symbol ?? edge.counterparty_inst_id,
        category: 1,
        symbolSize: 22 + Math.abs(Number(edge.coefficient)) * 18,
        itemStyle: {
          color: theme.surface,
          borderColor: theme.text,
          borderWidth: 1,
        },
      })),
    ];

    const edges = payload.edges.map((edge, index) => {
      const datum = edgeDatum(edge, index);
      const magnitude = Math.min(1, Math.abs(datum.coefficient));
      const counterpartyLeads = edge.best_lag > 0;
      return {
        source: counterpartyLeads ? edge.counterparty_inst_id : targetNodeId,
        target: counterpartyLeads ? targetNodeId : edge.counterparty_inst_id,
        symbol: edge.best_lag === 0 ? ["none", "none"] : ["none", "arrow"],
        symbolSize: 7,
        lineStyle: {
          color: datum.coefficient >= 0 ? theme.positive : theme.negative,
          width: 1 + magnitude * 3.5,
          opacity: 0.35 + magnitude * 0.5,
          curveness: 0.08,
        },
        datum,
      };
    });

    const series = {
      type: "graph",
      layout: "force",
      roam: true,
      draggable: false,
      symbol: "circle",
      force: { repulsion: 320, edgeLength: [110, 190], gravity: 0.12 },
      categories: [{ name: "目标" }, { name: "关联标的" }],
      label: {
        show: true,
        position: "right",
        color: theme.text,
        fontSize: 12,
      },
      emphasis: {
        focus: "adjacency",
        label: { show: true, color: theme.strongText },
      },
      lineStyle: { curveness: 0.08 },
      data: nodes,
      edges,
    };

    // ECharts 允许在节点/边数据上携带自定义字段供 tooltip 使用，
    // 其类型定义没有对应索引签名，因此这里只在此处做一次收窄转换。
    return {
      backgroundColor: "transparent",
      animationDuration: 420,
      tooltip: {
        confine: true,
        backgroundColor: theme.surface,
        borderColor: theme.border,
        textStyle: { color: theme.strongText, fontSize: 12 },
        formatter: (params: unknown) => {
          const item = params as { dataType?: string; data?: Record<string, unknown> };
          const data = item.data ?? {};
          if (item.dataType === "node") {
            return `<strong>${String(data.name ?? "")}</strong>`;
          }
          const datum = data.datum as EdgeDatum | undefined;
          if (!datum) {
            return "";
          }
          return [
            `<strong>${datum.counterpartySymbol}</strong>`,
            `系数 ${datum.coefficientText}`,
            `滞后 ${datum.lagText}`,
            `稳定性 ${datum.stabilityText}`,
            `p 值 ${datum.pValueText}`,
          ].join("<br/>");
        },
      },
      series: [series],
    } as unknown as EChartsOption;
  }, [payload.edges, target.symbol, targetNodeId, theme]);

  const handleClick = useCallback(
    (params: ChartClickParams) => {
      if (params.dataType === "edge") {
        const data = params.data as { datum?: EdgeDatum } | undefined;
        if (data?.datum) {
          setSelectedIndex(data.datum.edgeIndex);
        }
        return;
      }
      if (params.dataType === "node") {
        const data = params.data as { id?: string } | undefined;
        if (data?.id && data.id !== targetNodeId) {
          onSelectCounterparty(data.id);
        }
      }
    },
    [onSelectCounterparty, targetNodeId],
  );

  const selectedEdge = selectedIndex === null ? null : (payload.edges[selectedIndex] ?? null);

  if (payload.edges.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-sm leading-6 text-muted-foreground">
        当前没有可展示的关系边（{payload.reason ?? "候选样本不足或系数未定义"}）。
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <Chart option={option} height={400} onClick={handleClick} />
      <p className="text-xs leading-5 text-muted-foreground">
        只读视图：滚轮/双指缩放，拖拽平移；悬停或点选连线查看系数、滞后与稳定性。箭头指向跟随的一方（
        <span className="whitespace-nowrap">best_lag &gt; 0 表示对手方领先目标</span>
        ）。
      </p>
      {selectedEdge ? (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-lg bg-muted/50 p-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-muted-foreground">对手方</dt>
            <dd className="font-medium">
              {selectedEdge.counterparty.symbol ?? selectedEdge.counterparty_inst_id}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">系数</dt>
            <dd className="font-mono">{formatDecimal(selectedEdge.coefficient)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">最佳滞后</dt>
            <dd>{lagLabel(selectedEdge.best_lag)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">稳定性</dt>
            <dd className="font-mono">{formatDecimal(selectedEdge.stability, 3)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">p 值</dt>
            <dd className="font-mono">{formatPValue(selectedEdge.p_value)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">排名</dt>
            <dd className="font-mono">#{selectedEdge.rank}</dd>
          </div>
        </dl>
      ) : null}
    </div>
  );
}
