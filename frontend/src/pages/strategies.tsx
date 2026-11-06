import { PageHeading, PendingPanel } from "../components/layout/page-parts";

export default function StrategiesPage() {
  return (
    <>
      <PageHeading
        eyebrow="Strategies"
        title="策略"
        description="组合策略、审批状态与回测评估报告。组合成员、交易方向与目标权重的调整必须经过人工批准。"
      />
      <PendingPanel
        stage="S6 / S7"
        title="策略数据区"
        items={[
          "方向性与相对价值策略列表",
          "多空组合成员与权重",
          "审批状态与审批记录",
          "历史回测与多周期评估",
          "用户自定义验证标准",
        ]}
      />
    </>
  );
}
