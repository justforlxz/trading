import { useEffect, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { formatBeijingTime, signedTone } from "../../lib/display";
import {
  accountSourceLabel,
  accountStatusLabel,
  fetchAccountSummary,
  fetchExchangePositions,
  marginModeLabel,
  marginUsageText,
  MISSING_VALUE,
  pnlText,
  positionSideLabel,
  syncAccount,
  uplRatioText,
  valueOrMissing,
  type AccountStatus,
  type AccountSummary,
  type ExchangePosition,
  type ExchangePositions,
} from "../../lib/positions";
import { cn } from "../../lib/utils";

function momentText(value: string | null | undefined): string {
  return value === null || value === undefined || value.trim() === ""
    ? MISSING_VALUE
    : formatBeijingTime(value);
}

function messageOf(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function Metric({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: string;
}) {
  return (
    <div className="min-w-0 rounded-md border px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={cn("mt-1 truncate font-mono text-base tabular-nums", tone)}
        title={value}
      >
        {value}
      </dd>
      {note ? <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{note}</p> : null}
    </div>
  );
}

function StatusNotice({
  status,
  asOf,
  subject,
}: {
  status: AccountStatus;
  asOf: string | null | undefined;
  subject: string;
}) {
  if (status === "ok") return null;

  const at = asOf ? momentText(asOf) : null;
  const text =
    status === "unconfigured"
      ? `未配置 OKX 密钥，无法刷新${subject}。${at ? `界面显示 ${at} 保存的历史快照。` : "当前没有可用的历史快照。"}`
      : `快照已过期。${at ? `最近快照时间 ${at}，请点击同步获取最新数据。` : `当前没有可用的${subject}。`}`;

  return (
    <p
      role="status"
      className="mb-4 rounded-md border border-amber-600/40 bg-amber-500/5 px-3 py-2 text-sm text-amber-700 dark:text-amber-400"
    >
      {text}
    </p>
  );
}

function ErrorNotice({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive"
    >
      {message}
    </p>
  );
}

function AccountCard({
  account,
  loading,
  syncing,
  syncError,
  onSync,
}: {
  account: AccountSummary | null;
  loading: boolean;
  syncing: boolean;
  syncError: string | null;
  onSync: () => void;
}) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1.5">
            <CardTitle>账户概览</CardTitle>
            <CardDescription>
              最近一次 OKX 只读账户快照；数值由后端提供，页面不计算盈亏或保证金比例。
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            className="shrink-0"
            disabled={syncing || loading}
            onClick={onSync}
          >
            {syncing ? "同步中…" : "同步 OKX"}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {syncError ? <ErrorNotice message={syncError} /> : null}

        {loading ? (
          <p className="text-sm text-muted-foreground">正在读取账户数据…</p>
        ) : account === null ? (
          <p className="text-sm text-muted-foreground">账户数据未返回。</p>
        ) : (
          <>
            <StatusNotice status={account.status} asOf={account.captured_at} subject="账户数据" />

            <dl className="grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-4">
              <Metric label="权益" value={valueOrMissing(account.equity)} />
              <Metric label="可用权益" value={valueOrMissing(account.available_equity)} />
              <Metric label="现金余额" value={valueOrMissing(account.cash_balance)} />
              <Metric
                label="未实现盈亏"
                value={pnlText(account.unrealized_pnl)}
                tone={account.unrealized_pnl == null ? undefined : signedTone(account.unrealized_pnl)}
              />
              <Metric label="已用保证金" value={valueOrMissing(account.used_margin)} />
              <Metric label="可用保证金" value={valueOrMissing(account.available_margin)} />
              <Metric label="保证金使用率" value={marginUsageText(account.margin_usage_pct)} />
              <Metric
                label="今日盈亏"
                value={pnlText(account.day_pnl)}
                tone={account.day_pnl == null ? undefined : signedTone(account.day_pnl)}
                note={
                  account.day_pnl == null
                    ? "后端未提供日初基准快照"
                    : "口径 equity_only：仅比较权益变化，未识别入金与出金"
                }
              />
            </dl>

            <p className="mt-4 text-xs text-muted-foreground">
              快照时间 {momentText(account.captured_at)} · 来源 {accountSourceLabel(account.source)}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

type Row = {
  key: string;
  value: string;
  tone?: string;
};

function positionRows(item: ExchangePosition): Row[] {
  return [
    { key: "size", value: valueOrMissing(item.size) },
    { key: "avg_px", value: valueOrMissing(item.avg_px) },
    { key: "mark_px", value: valueOrMissing(item.mark_px) },
    {
      key: "upl",
      value: pnlText(item.upl),
      ...(item.upl == null ? {} : { tone: signedTone(item.upl) }),
    },
    { key: "upl_ratio", value: uplRatioText(item.upl_ratio) },
    { key: "lever", value: valueOrMissing(item.lever) },
    { key: "mgn_mode", value: marginModeLabel(item.mgn_mode) },
    { key: "liq_px", value: valueOrMissing(item.liq_px) },
    { key: "margin", value: valueOrMissing(item.margin) },
  ];
}

function ExchangeTable({ items }: { items: ExchangePosition[] }) {
  return (
    <div className="min-w-0 overflow-x-auto">
      <table className="w-full min-w-[980px] text-left text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="py-2 pr-3 font-medium">标的</th>
            <th className="px-2 py-2 font-medium">方向</th>
            <th className="px-2 py-2 text-right font-medium">数量</th>
            <th className="px-2 py-2 text-right font-medium">开仓均价</th>
            <th className="px-2 py-2 text-right font-medium">标记价</th>
            <th className="px-2 py-2 text-right font-medium">未实现盈亏</th>
            <th className="px-2 py-2 text-right font-medium">盈亏率</th>
            <th className="px-2 py-2 text-right font-medium">杠杆</th>
            <th className="hidden px-2 py-2 font-medium lg:table-cell">保证金模式</th>
            <th className="hidden px-2 py-2 text-right font-medium lg:table-cell">强平价</th>
            <th className="hidden px-2 py-2 text-right font-medium lg:table-cell">保证金</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const values = new Map(positionRows(item).map((row) => [row.key, row]));
            return (
              <tr key={item.pos_id} className="border-b last:border-0">
                <td className="py-3 pr-3">
                  <span className="font-mono font-medium">{item.display_symbol}</span>
                  <span className="block text-xs text-muted-foreground">{item.name}</span>
                </td>
                <td className="px-2 py-3">
                  <span
                    className={cn(
                      "rounded-full border px-2 py-0.5 text-xs font-medium",
                      item.pos_side === "short"
                        ? "border-rose-600/40 text-rose-600 dark:text-rose-400"
                        : "border-emerald-600/40 text-emerald-600 dark:text-emerald-400",
                    )}
                  >
                    {positionSideLabel(item.pos_side)}
                  </span>
                </td>
                <td className="px-2 py-3 text-right font-mono tabular-nums">
                  {values.get("size")?.value}
                </td>
                <td className="px-2 py-3 text-right font-mono tabular-nums">
                  {values.get("avg_px")?.value}
                </td>
                <td className="px-2 py-3 text-right font-mono tabular-nums">
                  {values.get("mark_px")?.value}
                </td>
                <td
                  className={cn(
                    "px-2 py-3 text-right font-mono tabular-nums",
                    values.get("upl")?.tone,
                  )}
                >
                  {values.get("upl")?.value}
                </td>
                <td className="px-2 py-3 text-right font-mono tabular-nums">
                  {values.get("upl_ratio")?.value}
                </td>
                <td className="px-2 py-3 text-right font-mono tabular-nums">
                  {values.get("lever")?.value}
                </td>
                <td className="hidden px-2 py-3 lg:table-cell">
                  {values.get("mgn_mode")?.value}
                </td>
                <td className="hidden px-2 py-3 text-right font-mono tabular-nums lg:table-cell">
                  {values.get("liq_px")?.value}
                </td>
                <td className="hidden px-2 py-3 text-right font-mono tabular-nums lg:table-cell">
                  {values.get("margin")?.value}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ExchangePositionsCard({
  positions,
  loading,
}: {
  positions: ExchangePositions | null;
  loading: boolean;
}) {
  const emptyText =
    positions?.status === "unconfigured"
      ? "未配置 OKX 密钥，暂无持仓数据。"
      : positions?.status === "stale"
        ? "快照已过期，暂无持仓数据。"
        : "暂无持仓";

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>OKX 交易所持仓</CardTitle>
        <CardDescription>
          只读快照；方向、数量、价格与盈亏均来自后端，页面不派生命中价值或保证金比例。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <p className="text-sm text-muted-foreground">正在读取交易所持仓…</p>
        ) : positions === null ? (
          <p className="text-sm text-muted-foreground">交易所持仓数据未返回。</p>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>状态：{accountStatusLabel(positions.status)}</span>
              <span>截至 {momentText(positions.as_of)}</span>
            </div>
            <StatusNotice status={positions.status} asOf={positions.as_of} subject="交易所持仓" />
            {positions.items.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">{emptyText}</p>
            ) : (
              <ExchangeTable items={positions.items} />
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

export type OkxSectionViewProps = {
  account: AccountSummary | null;
  positions: ExchangePositions | null;
  loading: boolean;
  error: string | null;
  syncError: string | null;
  syncing: boolean;
  onSync: () => void;
  onRetry: () => void;
};

/** 纯展示组件：测试直接渲染它，不依赖网络与浏览器。 */
export function OkxSectionView({
  account,
  positions,
  loading,
  error,
  syncError,
  syncing,
  onSync,
  onRetry,
}: OkxSectionViewProps) {
  if (error && account === null && positions === null) {
    return (
      <Card>
        <CardContent className="space-y-3 pt-6">
          <ErrorNotice message={error} />
          <Button type="button" variant="outline" onClick={onRetry}>
            重试
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <section className="grid min-w-0 gap-4" aria-label="OKX 账户与持仓">
      {error ? <ErrorNotice message={error} /> : null}
      <AccountCard
        account={account}
        loading={loading && account === null}
        syncing={syncing}
        syncError={syncError}
        onSync={onSync}
      />
      <ExchangePositionsCard positions={positions} loading={loading && positions === null} />
    </section>
  );
}

export default function OkxSection() {
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [positions, setPositions] = useState<ExchangePositions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    Promise.all([fetchAccountSummary(), fetchExchangePositions()])
      .then(([summary, exchange]) => {
        if (!active) return;
        setAccount(summary);
        setPositions(exchange);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(messageOf(reason, "账户与持仓数据加载失败"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [reloadToken]);

  const handleSync = async () => {
    setSyncing(true);
    setSyncError(null);
    try {
      const summary = await syncAccount();
      setAccount(summary);
      try {
        setPositions(await fetchExchangePositions());
      } catch (reason: unknown) {
        setSyncError(`同步完成，但持仓表刷新失败：${messageOf(reason, "未知错误")}`);
      }
    } catch (reason: unknown) {
      setSyncError(`同步失败，仍显示上一次快照：${messageOf(reason, "未知错误")}`);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <OkxSectionView
      account={account}
      positions={positions}
      loading={loading}
      error={error}
      syncError={syncError}
      syncing={syncing}
      onSync={() => void handleSync()}
      onRetry={() => setReloadToken((token) => token + 1)}
    />
  );
}
