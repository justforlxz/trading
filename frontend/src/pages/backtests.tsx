import { PageHeading, PendingPanel } from "../components/layout/page-parts";

export default function BacktestsPage() {
  return (
    <>
      <PageHeading
        eyebrow="Backtests"
        title="回测"
        description="历史回测与量化验证：收益率、回撤、夏普、胜率与交易次数都由后端计算并返回。"
      />
      <PendingPanel
        stage="P1"
        title="回测与验证"
        items={["回测任务与进度", "权益曲线与指标报告", "用户自定义验证标准"]}
      />
    </>
  );
}
