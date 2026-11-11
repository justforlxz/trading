/**
 * 关系网络的几何计算。
 *
 * 只做「把节点摆到 SVG 坐标上、把边连起来」这一件呈现工作：不计算相关性、不做力
 * 导向模拟、也不补造缺失的节点或边。布局按社区分组：同一社区的点摆在同一个小圆环
 * 上，社区中心再排在一个大圆上，因此同一份数据每次画出的位置完全相同，截图可复现。
 *
 * 摆位只用节点与边的数据，不看渲染尺寸：SVG 用 viewBox 等比缩放，布局与视口无关。
 */

import type { RelationEdge, RelationNode } from "./api";

export const GRAPH_WIDTH = 900;
export const GRAPH_HEIGHT = 520;
export const NODE_RADIUS = 7;

const CENTER = { x: GRAPH_WIDTH / 2, y: GRAPH_HEIGHT / 2 };
const SHORT_SIDE = Math.min(GRAPH_WIDTH, GRAPH_HEIGHT);
/** 社区中心所在大圆的半径：留出成员圆环与标签的位置，点不会顶到画布边缘。 */
const HUB_RADIUS = SHORT_SIDE * 0.3;
/** 成员圆环随人数增长，但不超过大圆的一个比例，避免社区之间互相压住。 */
const MEMBER_BASE_RADIUS = 22;
const MEMBER_STEP_RADIUS = 14;
const MEMBER_MAX_RATIO = 0.42;

export type PlacedNode = {
  productKey: string;
  communityId: number;
  degree: number;
  centrality: string;
  x: number;
  y: number;
};

export type PlacedEdge = {
  productKeyA: string;
  productKeyB: string;
  coefficient: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

export type PlacedGraph = {
  nodes: PlacedNode[];
  edges: PlacedEdge[];
  communities: Array<{ communityId: number; productKeys: string[] }>;
};

/** 一个节点的全部邻居；自环在服务端已被拒绝，这里同样忽略。 */
export function neighborsOf(key: string, edges: RelationEdge[]): string[] {
  const found = new Set<string>();
  for (const edge of edges) {
    if (edge.product_key_a === key && edge.product_key_b !== key) found.add(edge.product_key_b);
    if (edge.product_key_b === key && edge.product_key_a !== key) found.add(edge.product_key_a);
  }
  return [...found].sort();
}

export function layoutGraph(nodes: RelationNode[], edges: RelationEdge[]): PlacedGraph {
  const byCommunity = new Map<number, RelationNode[]>();
  for (const node of nodes) {
    const bucket = byCommunity.get(node.community_id) ?? [];
    bucket.push(node);
    byCommunity.set(node.community_id, bucket);
  }
  for (const bucket of byCommunity.values()) {
    bucket.sort((left, right) => left.product_key.localeCompare(right.product_key));
  }

  const communityIds = [...byCommunity.keys()].sort((left, right) => left - right);
  const positions = new Map<string, { x: number; y: number }>();
  if (communityIds.length === 1) {
    // 只有一个社区时不画「一个中心 + 一圈成员」的空心结构，直接摆成一圈；
    // 只有一个节点时半径取 0，也就是摆在画布正中。
    const members = byCommunity.get(communityIds[0]) ?? [];
    placeRing(CENTER, members.length === 1 ? 0 : HUB_RADIUS, members, positions);
  } else {
    communityIds.forEach((communityId, index) => {
      const angle = -Math.PI / 2 + (2 * Math.PI * index) / communityIds.length;
      const hub = {
        x: CENTER.x + Math.cos(angle) * HUB_RADIUS,
        y: CENTER.y + Math.sin(angle) * HUB_RADIUS,
      };
      const members = byCommunity.get(communityId) ?? [];
      if (members.length === 1) {
        positions.set(members[0].product_key, hub);
        return;
      }
      const radius = Math.min(
        MEMBER_BASE_RADIUS + (members.length - 1) * MEMBER_STEP_RADIUS,
        HUB_RADIUS * MEMBER_MAX_RATIO,
      );
      placeRing(hub, radius, members, positions);
    });
  }

  const placedNodes: PlacedNode[] = [...nodes]
    .sort((left, right) => left.product_key.localeCompare(right.product_key))
    .map((node) => {
      const position = positions.get(node.product_key) ?? CENTER;
      return {
        productKey: node.product_key,
        communityId: node.community_id,
        degree: node.degree,
        centrality: node.centrality,
        x: position.x,
        y: position.y,
      };
    });

  const placedEdges: PlacedEdge[] = [];
  for (const edge of edges) {
    const start = positions.get(edge.product_key_a);
    const end = positions.get(edge.product_key_b);
    if (start === undefined || end === undefined) continue;
    placedEdges.push({
      productKeyA: edge.product_key_a,
      productKeyB: edge.product_key_b,
      coefficient: Number(edge.coefficient),
      x1: start.x,
      y1: start.y,
      x2: end.x,
      y2: end.y,
    });
  }

  return {
    nodes: placedNodes,
    edges: placedEdges,
    communities: communityIds.map((communityId) => ({
      communityId,
      productKeys: (byCommunity.get(communityId) ?? []).map((node) => node.product_key),
    })),
  };
}

function placeRing(
  hub: { x: number; y: number },
  radius: number,
  members: RelationNode[],
  positions: Map<string, { x: number; y: number }>,
): void {
  members.forEach((node, index) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * index) / Math.max(members.length, 1);
    positions.set(node.product_key, {
      x: hub.x + Math.cos(angle) * radius,
      y: hub.y + Math.sin(angle) * radius,
    });
  });
}
