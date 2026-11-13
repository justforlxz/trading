import { PageHeading, PendingPanel } from "../components/layout/page-parts";

/**
 * 持仓页骨架。这里只说明后续节点会交付什么，不展示任何持仓或盈亏数值。
 */
export default function PositionsPage() {
  return (
    <>
      <PageHeading
        eyebrow="Positions"
        title="持仓"
        description="集中查看 OKX 只读持仓与手动记录的持仓，并据此检查组合敞口与风险。"
      />
      <PendingPanel
        stage="S2-1 / S2-2"
        title="持仓页计划交付"
        items={[
          "OKX 持仓只读：合约、方向、杠杆、未实现盈亏、标记价与止损距离。",
          "手动持仓：创建、买入、卖出与成本重算，每次操作保留可追溯的记录。",
          "敞口与风险提示：总敞口、净敞口、集中度，以及每条风险对应的输入字段和规则。",
          "数据状态：区分交易所同步值与手动记录值，并标明各自的时间与来源。",
        ]}
      />
    </>
  );
}
