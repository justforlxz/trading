import { PageHeading, PendingPanel } from "../components/layout/page-parts";

export default function WatchlistPage() {
  return (
    <>
      <PageHeading
        eyebrow="Watchlist"
        title="自选"
        description="用户关注的标的及其分组，是所有分析与策略的输入起点。"
      />
      <PendingPanel
        stage="P1"
        title="自选目标管理"
        items={["按分组维护标的", "合约元数据与交易状态", "与现货价格的对照"]}
      />
    </>
  );
}
