import { useCallback, useState } from "react";

import { PageHeading } from "../components/layout/page-parts";
import type { AccountSummary } from "../lib/positions";
import ManualSection from "./positions/manual-section";
import OkxSection from "./positions/okx-section";
import { PositionsOverviewStripView } from "./positions/overview-strip";
import RiskSection from "./positions/risk-section";

/**
 * 持仓页只负责组合概览、风险、账户与手动持仓区域；各区域的业务状态放在各自组件里。
 */
export default function PositionsPage() {
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [accountLoading, setAccountLoading] = useState(true);
  const handleAccountChange = useCallback(
    (next: AccountSummary | null, loading: boolean) => {
      setAccount(next);
      setAccountLoading(loading);
    },
    [],
  );

  return (
    <>
      <PageHeading
        eyebrow="Positions"
        title="持仓"
        description="集中查看 OKX 只读持仓与手动记录的持仓，并据此检查组合敞口与风险。"
      />
      <div className="grid gap-4">
        <PositionsOverviewStripView account={account} loading={accountLoading} />
        <RiskSection />
        <OkxSection onAccountChange={handleAccountChange} />
        <ManualSection />
      </div>
    </>
  );
}
