import { PageHeading, PendingPanel } from "../components/layout/page-parts";

/**
 * 记录页骨架。这里只说明后续节点会交付什么，不展示任何统计或演示数值。
 */
export default function JournalPage() {
  return (
    <>
      <PageHeading
        eyebrow="Journal"
        title="记录"
        description="保存研究假设、结论、决策与复盘，并把每条记录关联到标的、策略或回测。"
      />
      <PendingPanel
        stage="S5-1 / S5-2"
        title="记录页计划交付"
        items={[
          "研究记录：假设、结论、决策与复盘的创建、编辑和删除。",
          "记录关联：每条记录可以关联标的、策略与回测，便于追溯判断依据。",
          "提醒与活动：由服务端事件表提供，页面只展示，不自行拼接或推测文案。",
          "时间线：按时间排列记录与事件，并标明来源和发生时间。",
        ]}
      />
    </>
  );
}
