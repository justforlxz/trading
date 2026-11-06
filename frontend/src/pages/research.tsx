import { PageHeading, PendingPanel } from "../components/layout/page-parts";

export default function ResearchPage() {
  return (
    <>
      <PageHeading
        eyebrow="Research"
        title="研究"
        description="以目标股票为分析锚点查看动态相关性、关系网络与相对强弱，并浏览全市场机会。关系网络只做分析展示，不承担策略编辑。"
      />
      <PendingPanel
        stage="S4 / S5"
        title="研究数据区"
        items={[
          "目标股票管理与详情",
          "动态相关性与关系快照",
          "关系网络图（只读）",
          "相对强弱与关系变化",
          "全市场机会列表",
        ]}
      />
    </>
  );
}
