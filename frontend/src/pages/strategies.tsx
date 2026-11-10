import { PageHeading, PendingPanel } from "../components/layout/page-parts";

export default function StrategiesPage() {
  return (
    <>
      <PageHeading
        eyebrow="Strategies"
        title="策略"
        description="信号、组合构建与审批状态机。新策略必须人工审批后才能进入验证流程。"
      />
      <PendingPanel
        stage="P1"
        title="策略与审批"
        items={["策略实例列表与状态", "组合成员与目标权重", "审批与驳回记录"]}
      />
    </>
  );
}
