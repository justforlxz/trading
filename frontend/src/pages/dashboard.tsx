import { PageHeading, PendingPanel } from "../components/layout/page-parts";

export default function DashboardPage() {
  return (
    <>
      <PageHeading
        eyebrow="Overview"
        title="市场驾驶舱"
        description="市场状态、涨跌广度与重点机会的单一入口。骨架阶段先固定信息层级：上部核心指标，中部趋势与机会，下部关联群体与策略状态。"
      />
      <PendingPanel
        stage="S5"
        title="驾驶舱数据区"
        items={[
          "市场状态与交易时段",
          "涨跌广度与指数口径",
          "重点机会（按分数排序，可下钻）",
          "关联股票群体",
          "策略运行情况与风险概览",
        ]}
      />
    </>
  );
}
