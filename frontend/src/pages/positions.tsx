import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "../components/ui/button";
import { PageHeading } from "../components/layout/page-parts";
import {
  dustHiddenText,
  fetchAccountSummary,
  fetchEquityCurve,
  fetchPositionCards,
  mergeAccountUpdate,
  mergeCardUpdates,
  syncAccount,
  type AccountSummary,
  type EquityCurve,
  type EquityRange,
  type PositionCards,
} from "../lib/positions";
import { fetchRiskExposure, type RiskExposure } from "../lib/risk";
import { fetchRiskNotifyConfig, type RiskNotifyRule } from "../lib/risk-notify";
import { usePositionStream } from "../lib/stream-hooks";
import AssetCardView from "./positions/asset-card";
import HitStripView from "./positions/hit-strip";
import ManualSection from "./positions/manual-section";
import OrderHistoryDialog from "./positions/order-history-dialog";
import PositionCardView from "./positions/position-card";
import RiskNotifyDialog from "./positions/risk-notify-dialog";

function messageOf(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

/**
 * 持仓页：资产卡 + 风控命中条 + 持仓卡片 + 手动持仓。
 *
 * 页面只负责取数与组合，所有数值（权益、名义、占比、保证金占用、止损距离）都由
 * 后端算好。页面唯一参与的计算是把曲线点映射成 SVG 坐标，属于纯几何换算。
 */
export default function PositionsPage() {
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [cards, setCards] = useState<PositionCards | null>(null);
  const [exposure, setExposure] = useState<RiskExposure | null>(null);
  const [curve, setCurve] = useState<EquityCurve | null>(null);
  const [range, setRange] = useState<EquityRange>("1d");
  const [rules, setRules] = useState<RiskNotifyRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [orderInstId, setOrderInstId] = useState<string | null>(null);

  const { positions: livePositions, account: liveAccount } = usePositionStream();
  const mergedAccount = useMemo(
    () => (account === null ? null : mergeAccountUpdate(account, liveAccount)),
    [account, liveAccount],
  );
  const mergedCards = useMemo(
    () => (cards === null ? null : mergeCardUpdates(cards, livePositions)),
    [cards, livePositions],
  );
  // 尘埃说明由后端给的条数决定；没有尘埃时不占位，页面也不自己估算阈值。
  const dustNote = mergedCards === null ? null : dustHiddenText(mergedCards.hidden_dust_count);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    Promise.all([
      fetchAccountSummary(),
      fetchPositionCards("1d"),
      fetchRiskExposure(),
      fetchRiskNotifyConfig(),
    ])
      .then(([summary, cardList, risk, notify]) => {
        if (!active) return;
        setAccount(summary);
        setCards(cardList);
        setExposure(risk);
        setRules(notify.rules);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(messageOf(reason, "持仓数据加载失败"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
    // 区间只影响权益曲线，其余区块不为切区间重取一遍。
  }, [reloadToken]);

  useEffect(() => {
    let active = true;
    fetchEquityCurve(range)
      .then((next) => {
        if (active) setCurve(next);
      })
      .catch(() => {
        // 曲线失败不影响其余区块；保持「读取曲线中…」而不是编一条线出来。
        if (active) setCurve(null);
      });
    return () => {
      active = false;
    };
  }, [range, reloadToken]);

  const refresh = useCallback(() => {
    setReloadToken((token) => token + 1);
  }, []);

  const handleSync = useCallback(async () => {
    setSyncing(true);
    setNotice(null);
    try {
      await syncAccount();
      setReloadToken((token) => token + 1);
    } catch (reason: unknown) {
      setNotice(`同步失败，仍显示上一次快照：${messageOf(reason, "未知错误")}`);
    } finally {
      setSyncing(false);
    }
  }, []);

  return (
    <>
      <PageHeading
        eyebrow="Portfolio"
        title="持仓"
        description="当前权益与收益曲线、每一条 OKX 持仓的盈亏与止损状态，以及手动记录的持仓。"
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              onClick={() => setSettingsOpen(true)}
            >
              风控通知设置
            </Button>
            <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
              刷新
            </Button>
            <Button size="sm" onClick={() => void handleSync()} disabled={syncing}>
              {syncing ? "同步中…" : "同步 OKX"}
            </Button>
          </div>
        }
      />

      {error === null ? null : (
        <p
          role="alert"
          className="mb-4 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive"
        >
          {error}
        </p>
      )}
      {notice === null ? null : (
        <p
          role="status"
          className="mb-4 rounded-md border border-amber-600/40 bg-amber-500/5 px-3 py-2 text-sm text-amber-700 dark:text-amber-400"
        >
          {notice}
        </p>
      )}

      <div className="grid gap-4">
        <AssetCardView
          account={mergedAccount}
          curve={curve}
          range={range}
          onRangeChange={setRange}
          loading={loading && mergedAccount === null}
        />

        <HitStripView exposure={exposure} onOpenSettings={() => setSettingsOpen(true)} />

        <section aria-label="OKX 持仓" className="mt-0">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="text-base font-semibold tracking-tight">
              OKX 持仓
              {mergedCards === null ? null : ` · ${mergedCards.items.length}`}
            </h2>
            <span className="text-[11px] text-muted-foreground">
              按未实现盈亏绝对值排序 · 卡片含盈亏曲线
            </span>
          </div>
          {dustNote === null ? null : (
            <p className="mt-1 text-[11px] text-muted-foreground">{dustNote}</p>
          )}

          {mergedCards === null ? (
            <p className="mt-2 rounded-md border px-3 py-6 text-center text-[11px] text-muted-foreground">
              读取持仓中…
            </p>
          ) : mergedCards.items.length === 0 ? (
            <p className="mt-2 rounded-md border px-3 py-6 text-center text-[11px] text-muted-foreground">
              暂无持仓。同步 OKX 后这里会列出每一条持仓。
            </p>
          ) : (
            <div className="mt-2 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {mergedCards.items.map((card) => (
                <PositionCardView
                  key={card.pos_id}
                  card={card}
                  onShowOrders={(instId) => setOrderInstId(instId)}
                />
              ))}
            </div>
          )}
        </section>

        <ManualSection />
      </div>

      <RiskNotifyDialog
        open={settingsOpen}
        rules={rules}
        onClose={() => setSettingsOpen(false)}
        onSaved={(next) => {
          setRules(next);
          refresh();
        }}
      />

      <OrderHistoryDialog instId={orderInstId} onClose={() => setOrderInstId(null)} />
    </>
  );
}
