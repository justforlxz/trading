import { useEffect, useState } from "react";

import { AlertList } from "../../components/ui/alert-list";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  fetchAlerts,
  updateAlertStatus,
  type AlertItem,
  type AlertStatusUpdate,
} from "../../lib/api";

function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : "提醒加载失败";
}

/**
 * 详情页提醒区：按当前标的取待处理提醒，确认或忽略后重新读取列表。
 * 文案、级别与规则标识都来自接口，不在页面里拼接。
 */
export function InstrumentAlertsCard({ instId }: { instId: string }) {
  const [items, setItems] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetchAlerts({ status: "pending", instrumentId: instId }, 100)
      .then((response) => {
        if (!active) return;
        setItems(response.items);
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
  }, [instId, refreshToken]);

  const resolve = async (alertId: string, status: AlertStatusUpdate): Promise<void> => {
    setResolvingId(alertId);
    setError(null);
    try {
      await updateAlertStatus(alertId, status);
      setRefreshToken((token) => token + 1);
    } catch (reason: unknown) {
      setError(messageOf(reason));
    } finally {
      setResolvingId(null);
    }
  };

  return (
    <Card data-section="instrument-alerts">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <CardTitle>提醒</CardTitle>
            <CardDescription>
              只显示当前标的的待处理提醒；确认或忽略后重新读取接口并写入活动流水。
            </CardDescription>
          </div>
          <span className="text-xs text-muted-foreground">
            {loading ? "正在加载…" : `${items.length} 条`}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {error ? (
          <p role="alert" className="mb-3 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
        {loading && items.length === 0 ? (
          <p className="text-sm text-muted-foreground">正在加载提醒…</p>
        ) : (
          <AlertList
            items={items}
            onResolve={(alertId, status) => {
              void resolve(alertId, status);
            }}
            resolvingId={resolvingId}
            emptyText="当前标的没有待处理提醒。"
          />
        )}
      </CardContent>
    </Card>
  );
}
