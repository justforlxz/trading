import { useEffect, useMemo, useState } from "react";

import {
  fetchDashboardSummary,
  withStreamUpdates,
  type DashboardPushed,
  type DashboardSummary,
} from "../lib/dashboard";
import { updateAlertStatus, type AlertStatusUpdate } from "../lib/api";
import { streamLiveness } from "../lib/stream";
import { usePositionStream, useQuoteStream, useStreamState } from "../lib/stream-hooks";
import { OverviewView } from "./overview/view";

function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : "读取首页汇总失败";
}

/** 首页 v6：一次取汇总，再按页面订阅把推送值合并到价格、持仓与账户上。 */
export default function OverviewPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);
  const [resolvingAlertId, setResolvingAlertId] = useState<string | null>(null);

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
      onRefresh={() => setReloadToken((token) => token + 1)}
      onResolveAlert={(alertId, status) => {
        void resolveAlert(alertId, status);
      }}
      resolvingAlertId={resolvingAlertId}
    />
  );
}
