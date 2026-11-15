import { signedTone } from "../../lib/display";
import {
  accountSourceLabel,
  accountStatusLabel,
  MISSING_VALUE,
  pnlText,
  valueOrMissing,
  type AccountSummary,
} from "../../lib/positions";
import { Metric } from "./metric";
import { momentText } from "./moment";

export type PositionsOverviewStripViewProps = {
  account: AccountSummary | null;
  loading: boolean;
};

/** 持仓页顶部概览条：四项都只展示后端字段，页面不做汇总或推算。 */
export function PositionsOverviewStripView({
  account,
  loading,
}: PositionsOverviewStripViewProps) {
  const missing = (text: string) => (loading ? "读取中…" : text);
  const captured = account === null ? MISSING_VALUE : momentText(account.captured_at);
  const marketValueAt =
    account === null ? MISSING_VALUE : momentText(account.position_notional_at);

  return (
    <section
      aria-label="持仓概览条"
      className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4"
    >
      <dl className="contents">
        <Metric
          size="lg"
          label="持仓市值"
          value={missing(valueOrMissing(account?.position_notional))}
          note={
            account?.position_notional == null
              ? loading
                ? "正在读取后端持仓汇总"
                : "后端未提供持仓市值汇总"
              : `来源：后端持仓快照 · 截至 ${marketValueAt}`
          }
        />
        <Metric
          size="lg"
          label="未实现盈亏"
          value={missing(pnlText(account?.unrealized_pnl))}
          tone={
            account?.unrealized_pnl == null ? undefined : signedTone(account.unrealized_pnl)
          }
          note={
            account === null
              ? "后端未返回账户快照"
              : `来源：OKX 账户快照 · 截至 ${captured}`
          }
        />
        <Metric
          size="lg"
          label="今日盈亏"
          value={missing(pnlText(account?.day_pnl))}
          tone={account?.day_pnl == null ? undefined : signedTone(account.day_pnl)}
          note={
            account === null
              ? "后端未返回账户快照"
              : account.day_pnl == null
                ? "后端未提供日初基准快照"
                : "来源：OKX 账户快照 · 基准 equity_only"
          }
        />
        <Metric
          size="lg"
          label="OKX 同步状态"
          value={account === null ? missing(MISSING_VALUE) : accountStatusLabel(account.status)}
          note={
            account === null
              ? "没有可用的同步状态"
              : `快照时间 ${captured} · 来源 ${accountSourceLabel(account.source)}`
          }
        />
      </dl>
    </section>
  );
}

export default PositionsOverviewStripView;
