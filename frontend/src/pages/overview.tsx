import { useEffect, useMemo, useState } from "react";

import {
  fetchDashboardSummary,
  withStreamUpdates,
  type DashboardPushed,
  type DashboardSummary,
} from "../lib/dashboard";
import {
  fetchAiSummary,
  fetchMacroOverview,
  fetchMarketOverview,
  fetchSettings,
  fetchWatchlist,
  updateAlertStatus,
  updateSettings,
  type AiSummaryResponse,
  type AlertStatusUpdate,
  type MacroOverviewResponse,
  type MarketSnapshotResponse,
} from "../lib/api";
import { pinnedCandidates, type PinnedCandidate } from "../lib/home-pinned";
import { streamLiveness } from "../lib/stream";
import { usePositionStream, useQuoteStream, useStreamState } from "../lib/stream-hooks";
import { OverviewView } from "./overview/view";

function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : "读取首页汇总失败";
}

function marketMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "读取市场概况失败";
}

function summaryMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "读取市场摘要失败";
}

function macroMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "读取宏观数据失败";
}

/** 首页 v6：一次取汇总，再按页面订阅把推送值合并到价格、持仓与账户上。 */
export default function OverviewPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);
  const [resolvingAlertId, setResolvingAlertId] = useState<string | null>(null);
  const [marketOverview, setMarketOverview] = useState<MarketSnapshotResponse | null>(null);
  const [marketOverviewError, setMarketOverviewError] = useState<string | null>(null);
  const [marketOverviewLoading, setMarketOverviewLoading] = useState(true);
  const [macroOverview, setMacroOverview] = useState<MacroOverviewResponse | null>(null);
  const [macroOverviewError, setMacroOverviewError] = useState<string | null>(null);
  const [macroOverviewLoading, setMacroOverviewLoading] = useState(true);
  const [aiSummary, setAiSummary] = useState<AiSummaryResponse | null>(null);
  const [aiSummaryError, setAiSummaryError] = useState<string | null>(null);
  const [aiSummaryLoading, setAiSummaryLoading] = useState(true);
  // 置顶清单存在服务端显示偏好里：首页读它，与当前自选求交集后决定卡片显示哪几行。
  const [pinnedWatchlist, setPinnedWatchlist] = useState<string[]>([]);
  // 弹窗候选来自整份自选：首页汇总只带五行，不够用来选第 6 个标的。
  const [watchlistCandidates, setWatchlistCandidates] = useState<PinnedCandidate[]>([]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetchDashboardSummary()
      .then((payload) => {
        if (!active) return;
        setSummary(payload);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(messageOf(reason));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reloadToken]);

  useEffect(() => {
    let active = true;
    setMarketOverviewLoading(true);
    setMarketOverview(null);
    setMarketOverviewError(null);
    fetchMarketOverview()
      .then((payload) => {
        if (!active) return;
        setMarketOverview(payload);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setMarketOverviewError(marketMessage(reason));
      })
      .finally(() => {
        if (active) setMarketOverviewLoading(false);
      });

    setMacroOverviewLoading(true);
    setMacroOverview(null);
    setMacroOverviewError(null);
    fetchMacroOverview()
      .then((payload) => {
        if (!active) return;
        setMacroOverview(payload);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setMacroOverviewError(macroMessage(reason));
      })
      .finally(() => {
        if (active) setMacroOverviewLoading(false);
      });

    setAiSummaryLoading(true);
    setAiSummary(null);
    setAiSummaryError(null);
    fetchAiSummary()
      .then((payload) => {
        if (!active) return;
        setAiSummary(payload);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setAiSummaryError(summaryMessage(reason));
      })
      .finally(() => {
        if (active) setAiSummaryLoading(false);
      });

    return () => {
      active = false;
    };
  }, [reloadToken]);

  useEffect(() => {
    let active = true;
    // 自选与设置都读不到时各自降级：置顶只是卡片的一个显示偏好，空清单/空候选都
    // 不会让首页整体不可用，用户点「选择标的」重新保存一次即可恢复。
    fetchWatchlist()
      .then((payload) => {
        if (active) setWatchlistCandidates(pinnedCandidates(payload.items));
      })
      .catch(() => undefined);
    fetchSettings()
      .then((settings) => {
        if (!active) return;
        setPinnedWatchlist(settings.display.homepage_pinned ?? []);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [reloadToken]);

  const savePinned = async (next: string[]): Promise<void> => {
    const saved = await updateSettings({ display: { homepage_pinned: next } });
    setPinnedWatchlist(saved.display.homepage_pinned ?? []);
  };

  const instIds = useMemo(
    () => (summary?.watchlist.data?.items ?? []).map((item) => item.inst_id),
    [summary],
  );
  const streamState = useStreamState();
  const quoteStream = useQuoteStream(instIds);
  const positionStream = usePositionStream();

  const merged = useMemo(
    () =>
      summary === null
        ? null
        : withStreamUpdates(summary, {
            quotes: quoteStream.quotes,
            positions: positionStream.positions,
            account: positionStream.account,
          }),
    [summary, quoteStream.quotes, positionStream.positions, positionStream.account],
  );

  const pushed: DashboardPushed = merged?.pushed ?? { account: null, positions: {}, watchlist: {} };

  const resolveAlert = async (alertId: string, status: AlertStatusUpdate): Promise<void> => {
    setResolvingAlertId(alertId);
    setError(null);
    try {
      await updateAlertStatus(alertId, status);
      setReloadToken((token) => token + 1);
    } catch (reason: unknown) {
      setError(messageOf(reason));
    } finally {
      setResolvingAlertId(null);
    }
  };

  return (
    <OverviewView
      summary={merged?.summary ?? null}
      error={error}
      loading={loading}
      priceLiveness={streamLiveness(streamState, "public_ws")}
      accountLiveness={streamLiveness(streamState, "private_ws")}
      pushed={pushed}
      marketOverview={marketOverview}
      marketOverviewError={marketOverviewError}
      marketOverviewLoading={marketOverviewLoading}
      macroOverview={macroOverview}
      macroOverviewError={macroOverviewError}
      macroOverviewLoading={macroOverviewLoading}
      aiSummary={aiSummary}
      aiSummaryError={aiSummaryError}
      aiSummaryLoading={aiSummaryLoading}
      onRefresh={() => setReloadToken((token) => token + 1)}
      onResolveAlert={(alertId, status) => {
        void resolveAlert(alertId, status);
      }}
      resolvingAlertId={resolvingAlertId}
      pinnedWatchlist={pinnedWatchlist}
      watchlistCandidates={watchlistCandidates}
      onSavePinned={savePinned}
    />
  );
}
