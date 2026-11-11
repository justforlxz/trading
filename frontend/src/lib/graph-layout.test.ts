import { describe, expect, it } from "vitest";

import type { RelationEdge, RelationNode } from "./api";
import { GRAPH_HEIGHT, GRAPH_WIDTH, layoutGraph, neighborsOf } from "./graph-layout";

function node(productKey: string, communityId: number, degree = 1): RelationNode {
  return {
    product_key: productKey,
    asset_type: "tokenized_equity",
    community_id: communityId,
    degree,
    centrality: "0.6667",
  };
}

function edge(a: string, b: string, coefficient: string): RelationEdge {
  return { product_key_a: a, product_key_b: b, coefficient, samples: 60 };
}

/** 契约示例那张四点图：两个社区各两点，四条边。 */
const NODES = [node("AAPL", 0, 2), node("MSFT", 0, 2), node("NVDA", 1, 3), node("TSLA", 1, 1)];
const EDGES = [
  edge("AAPL", "MSFT", "0.87"),
  edge("AAPL", "NVDA", "-0.64"),
  edge("MSFT", "NVDA", "-0.64"),
  edge("NVDA", "TSLA", "0.58"),
];

describe("关系网络布局", () => {
  it("同一份数据每次摆到同一个位置", () => {
    expect(layoutGraph(NODES, EDGES)).toEqual(layoutGraph(NODES, EDGES));
  });

  it("节点按产品键排序，每个节点只出现一次", () => {
    const layout = layoutGraph(NODES, EDGES);

    expect(layout.nodes.map((row) => row.productKey)).toEqual([
      "AAPL",
      "MSFT",
      "NVDA",
      "TSLA",
    ]);
  });

  it("所有节点落在画布之内", () => {
    const layout = layoutGraph(NODES, EDGES);

    for (const row of layout.nodes) {
      expect(row.x).toBeGreaterThanOrEqual(0);
      expect(row.x).toBeLessThanOrEqual(GRAPH_WIDTH);
      expect(row.y).toBeGreaterThanOrEqual(0);
      expect(row.y).toBeLessThanOrEqual(GRAPH_HEIGHT);
    }
  });

  it("同一张图里没有两个节点重叠", () => {
    const layout = layoutGraph(NODES, EDGES);
    const seen = new Set(layout.nodes.map((row) => `${row.x},${row.y}`));

    expect(seen.size).toBe(layout.nodes.length);
  });

  it("边的两端与节点的坐标完全一致", () => {
    const layout = layoutGraph(NODES, EDGES);
    const position = new Map(layout.nodes.map((row) => [row.productKey, row]));

    for (const row of layout.edges) {
      expect(row.x1).toBe(position.get(row.productKeyA)?.x);
      expect(row.y1).toBe(position.get(row.productKeyA)?.y);
      expect(row.x2).toBe(position.get(row.productKeyB)?.x);
      expect(row.y2).toBe(position.get(row.productKeyB)?.y);
    }
  });

  it("系数原样转成数字，不做正负或大小处理", () => {
    const layout = layoutGraph(NODES, EDGES);

    expect(layout.edges.map((row) => row.coefficient)).toEqual([0.87, -0.64, -0.64, 0.58]);
  });

  it("社区按编号排序，成员按产品键排序", () => {
    const layout = layoutGraph(NODES, EDGES);

    expect(layout.communities).toEqual([
      { communityId: 0, productKeys: ["AAPL", "MSFT"] },
      { communityId: 1, productKeys: ["NVDA", "TSLA"] },
    ]);
  });

  it("单个节点摆在画布中心", () => {
    const layout = layoutGraph([node("AAPL", 0, 0)], []);

    expect(layout.nodes).toHaveLength(1);
    expect(layout.nodes[0].x).toBe(GRAPH_WIDTH / 2);
    expect(layout.nodes[0].y).toBe(GRAPH_HEIGHT / 2);
    expect(layout.edges).toEqual([]);
  });

  it("只有一个社区时全部节点摆在同一个圆环上", () => {
    const nodes = [node("AAPL", 0), node("MSFT", 0), node("NVDA", 0)];
    const layout = layoutGraph(nodes, []);

    const distances = layout.nodes.map((row) =>
      Math.hypot(row.x - GRAPH_WIDTH / 2, row.y - GRAPH_HEIGHT / 2),
    );
    expect(new Set(distances.map((value) => value.toFixed(6))).size).toBe(1);
  });

  it("空图得到空布局", () => {
    expect(layoutGraph([], [])).toEqual({ nodes: [], edges: [], communities: [] });
  });

  it("端点不在节点表里的边被丢弃（不画悬空边）", () => {
    const layout = layoutGraph([node("AAPL", 0)], [edge("AAPL", "NVDA", "0.9")]);

    expect(layout.edges).toEqual([]);
  });
});

describe("邻居查询", () => {
  it("两端都算邻居，且按产品键排序", () => {
    expect(neighborsOf("AAPL", EDGES)).toEqual(["MSFT", "NVDA"]);
    expect(neighborsOf("NVDA", EDGES)).toEqual(["AAPL", "MSFT", "TSLA"]);
  });

  it("没有边的节点没有邻居", () => {
    expect(neighborsOf("TSLA", [])).toEqual([]);
  });
});
