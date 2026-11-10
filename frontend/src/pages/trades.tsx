import { PageHeading, PendingPanel } from "../components/layout/page-parts";

export default function TradesPage() {
  return (
    <>
      <PageHeading
        eyebrow="Trades"
        title="交易"
        description="订单、成交与持仓。真实交易默认关闭，未获用户授权不会下单。"
      />
      <PendingPanel
        stage="P3"
        title="交易监控"
        items={["订单与成交记录", "持仓与策略归属", "账户对账与故障恢复"]}
      />
    </>
  );
}
