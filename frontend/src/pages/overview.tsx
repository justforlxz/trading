import { PageHeading, PendingPanel } from "../components/layout/page-parts";

/**
 * 概览页骨架。后端聚合接口已由 `GET /api/dashboard/summary` 提供，
 * 页面本身由 S4-1 重写；这里只说明计划交付内容，不展示任何演示数值。
 */
export default function OverviewPage() {
  return (
    <>
      <PageHeading
        eyebrow="Overview"
        title="概览"
        description="一屏查看市场、账户、风险、持仓、自选、提醒、策略与最近活动。"
      />
      <PendingPanel
        stage="S4-1"
        title="概览页计划交付"
        items={[
          "市场概况：按标的类别展示广度、共振与当前交易时段，并标明行情来源。",
          "账户与风险：权益、保证金使用率、综合风险等级与规则命中数量。",
          "持仓与自选：最多显示几行摘要，完整明细分别进入持仓页与自选页。",
          "提醒与活动：只展示未处理提醒与最近活动，由服务端事件表提供。",
        ]}
      />
    </>
  );
}
