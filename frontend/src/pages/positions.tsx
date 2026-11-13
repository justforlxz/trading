import { PageHeading } from "../components/layout/page-parts";
import ManualSection from "./positions/manual-section";
import OkxSection from "./positions/okx-section";

/**
 * 持仓页只负责组合两个区域；账户与持仓的业务状态分别放在各自组件里。
 */
export default function PositionsPage() {
  return (
    <>
      <PageHeading
        eyebrow="Positions"
        title="持仓"
        description="集中查看 OKX 只读持仓与手动记录的持仓，并据此检查组合敞口与风险。"
      />
      <div className="grid gap-4">
        <OkxSection />
        <ManualSection />
      </div>
    </>
  );
}
