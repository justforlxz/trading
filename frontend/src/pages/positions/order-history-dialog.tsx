import { useEffect, useState } from "react";

import { Button } from "../../components/ui/button";
import { Dialog } from "../../components/ui/dialog";
import {
  fetchInstrumentOrders,
  orderSideLabel,
  orderStatusLabel,
  ORDER_SCOPES,
  valueOrMissing,
  type OrderHistory,
  type OrderScope,
} from "../../lib/positions";
import { cn } from "../../lib/utils";

export type OrderHistoryDialogProps = {
  instId: string | null;
  onClose: () => void;
};

/** 失败态对用户说的话：只说「取不到」，不解释内部实现。 */
export const ORDER_HISTORY_ERROR_TEXT = "暂时取不到订单历史";

export type OrderHistoryBodyProps = {
  data: OrderHistory | null;
  loading: boolean;
  /** 失败原因；只放进 `title` 供排障，不直接渲染。 */
  error: string | null;
  onRetry: () => void;
};

/**
 * 单标的订单历史弹窗：近 7 天来自 `orders-history`，更早来自归档（最多 3 个月）。
 *
 * 「挂单」与「历史」用后端返回的 `is_open` 区分，前端不按状态名猜。没有订单时给
 * 空态文案；上游失败时给可读文案 + 「重试」——空列表只代表「确实没有订单」，
 * 失败必须与它区分开，否则用户没法判断该等一等还是该换个标的。
 *
 * 失败原因（可能是接口路径、errno、异常原文）只放进 `title`，不上屏。
 */
export function OrderHistoryDialog({ instId, onClose }: OrderHistoryDialogProps) {
  const [scope, setScope] = useState<OrderScope>("all");
  const [data, setData] = useState<OrderHistory | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (instId === null) return;
    setScope("all");
  }, [instId]);

  useEffect(() => {
    if (instId === null) {
      setData(null);
      setError(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    fetchInstrumentOrders(instId, scope)
      .then((history) => {
        if (active) setData(history);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setData(null);
        setError(reason instanceof Error ? reason.message : "订单历史加载失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [instId, scope, reloadToken]);

  return (
    <Dialog
      open={instId !== null}
      title={instId === null ? "订单历史" : `${instId} 订单历史`}
      description={
        data === null
          ? "近 7 天来自 orders-history，更早来自归档（最多 3 个月）"
          : `共 ${data.items.length} 笔 · 近 ${data.window_days} 天与归档合并，按时间倒序`
      }
      maxWidth="40rem"
      onClose={onClose}
      footer={
        <>
          <span className="text-[11px] text-muted-foreground">
            近 7 天来自 orders-history，更早来自 orders-history-archive（最多 3 个月）
          </span>
          <Button size="sm" onClick={onClose}>
            关闭
          </Button>
        </>
      }
    >
      <div className="px-6">
        <div className="flex items-center gap-1" role="tablist" aria-label="订单筛选">
          {ORDER_SCOPES.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={item.key === scope}
              onClick={() => setScope(item.key)}
              className={cn(
                "h-7 rounded-md px-2 text-[11px] font-medium transition-colors",
                item.key === scope
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              {item.label}
            </button>
          ))}
          <span className="ml-auto text-[11px] text-muted-foreground">按时间倒序</span>
        </div>
      </div>

      <OrderHistoryBody
        data={data}
        loading={loading}
        error={error}
        onRetry={() => setReloadToken((token) => token + 1)}
      />
    </Dialog>
  );
}

/** 弹窗主体：加载中 / 失败 / 空态 / 列表四态，纯展示。 */
export function OrderHistoryBody({ data, loading, error, onRetry }: OrderHistoryBodyProps) {
  return (
    <div className="px-6 py-2" style={{ maxHeight: "26rem", overflowY: "auto" }}>
      {error !== null ? (
        <div className="py-8 text-center" role="alert" title={error}>
          <p className="text-xs text-muted-foreground">{ORDER_HISTORY_ERROR_TEXT}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
            重试
          </Button>
        </div>
      ) : loading ? (
        <p className="py-8 text-center text-xs text-muted-foreground">读取中…</p>
      ) : data === null || data.items.length === 0 ? (
        <p className="py-8 text-center text-xs text-muted-foreground">该分类下没有订单</p>
      ) : (
        data.items.map((item) => (
          <div key={item.order_id} className="border-b py-2 text-xs last:border-0">
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-mono text-[11px] text-muted-foreground">
                {item.ts.slice(0, 16).replace("T", " ")}
              </span>
              <span className="text-[11px] text-muted-foreground">
                {orderStatusLabel(item.status)}
              </span>
            </div>
            <div className="mt-0.5 flex items-baseline justify-between gap-2">
              <span>
                {orderSideLabel(item.side)} · 均价{" "}
                <span className="font-mono tabular-nums">{valueOrMissing(item.avg_px)}</span> ·
                数量 <span className="font-mono tabular-nums">{item.qty}</span>
              </span>
              <span className={cn("font-mono tabular-nums", pnlTone(item.pnl))}>
                {valueOrMissing(item.pnl)}
              </span>
            </div>
            <div className="mt-0.5 text-[11px] text-muted-foreground">
              手续费 {valueOrMissing(item.fee)} · 类型 {item.order_type}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

function pnlTone(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") {
    return "text-muted-foreground";
  }
  return value.trim().startsWith("-")
    ? "text-rose-600 dark:text-rose-400"
    : "text-emerald-600 dark:text-emerald-400";
}

export default OrderHistoryDialog;
