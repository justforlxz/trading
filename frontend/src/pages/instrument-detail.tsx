import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { CandlestickChart } from "../components/chart/candlestick-chart";
import { PageHeading } from "../components/layout/page-parts";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import {
  fetchCandles,
  fetchInstrumentDetail,
  type CandleBar,
  type CandleSeriesResponse,
  type InstrumentDetailResponse,
} from "../lib/api";
import { instTypeLabel, signalTone, signedTone, signedValue } from "../lib/display";
import { cn } from "../lib/utils";

const BAR_OPTIONS: CandleBar[] = ["1m", "5m", "15m", "1h", "4h", "1d"];

/** 默认周期与契约默认值一致；切换形态时页面不重建，周期因此保持不变。 */
const DEFAULT_BAR: CandleBar = "1h";

export default function InstrumentDetailPage() {
  const { instId = "" } = useParams<{ instId: string }>();
  const [detail, setDetail] = useState<InstrumentDetailResponse | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [bar, setBar] = useState<CandleBar>(DEFAULT_BAR);
  const [series, setSeries] = useState<CandleSeriesResponse | null>(null);
  const [seriesError, setSeriesError] = useState<string | null>(null);

  useEffect(() => {
    if (!instId) return;
    let active = true;
    setDetail(null);
    setDetailError(null);
    fetchInstrumentDetail(instId)
      .then((value) => {
        if (active) setDetail(value);
      })
      .catch((reason: unknown) => {
        if (active) setDetailError(reason instanceof Error ? reason.message : "标的加载失败");
      });
    return () => {
      active = false;
    };
  }, [instId]);

  useEffect(() => {
    if (!instId) return;
    let active = true;
    setSeries(null);
    setSeriesError(null);
    fetchCandles(instId, bar)
      .then((value) => {
        if (active) setSeries(value);
      })
      .catch((reason: unknown) => {
        if (active) setSeriesError(reason instanceof Error ? reason.message : "K 线加载失败");
      });
    return () => {
      active = false;
    };
  }, [instId, bar]);

  const instrument = detail?.instrument;
  const signal = detail?.latest_signal ?? null;
  const lastCandle = series?.candles.at(-1) ?? null;

  const meta = instrument
    ? [
        { label: "产品", value: instrument.product_key },
        { label: "形态", value: instTypeLabel(instrument.inst_type) },
        { label: "交易状态", value: instrument.trading_status },
        { label: "资产类型", value: instrument.asset_type },
        { label: "计价", value: `${instrument.base_currency} / ${instrument.quote_currency}` },
        { label: "最小价格变动", value: instrument.tick_size },
        { label: "最小下单量", value: instrument.min_order_size },
        { label: "上市时间", value: instrument.listing_time },
        ...(instrument.max_leverage ? [{ label: "最大杠杆", value: instrument.max_leverage }] : []),
      ]
    : [];

  return (
    <>
      <Link
        to="/watchlist"
        className="mb-6 inline-flex items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
      >
        ← 返回自选
      </Link>

      <PageHeading
        eyebrow="Instrument"
        title={instId}
        description="合约元数据、同一产品的其他形态与 K 线；形态切换只更换交易标的，K 线周期保持不变。"
      />

      {detailError ? (
        <p className="mb-6 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {detailError}
        </p>
      ) : null}

      {!detailError && !detail ? (
        <p className="mb-6 text-sm text-muted-foreground">加载中…</p>
      ) : null}

      {instrument ? (
        <div className="grid gap-6">
          <Card>
            <CardHeader>
              <CardTitle>合约元数据</CardTitle>
              <CardDescription>字段与取值原样来自标的接口，不做前端换算。</CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-4 text-sm sm:grid-cols-3">
                {meta.map((field) => (
                  <div key={field.label} className="grid gap-1">
                    <dt className="text-muted-foreground">{field.label}</dt>
                    <dd className="font-mono text-xs">{field.value}</dd>
                  </div>
                ))}
              </dl>

              <div className="mt-6 border-t pt-4">
                <p className="mb-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
                  最新信号
                </p>
                {signal ? (
                  <div className="flex flex-wrap items-center gap-3 text-sm">
                    <span
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-xs font-medium",
                        signalTone(signal.action),
                      )}
                    >
                      {signal.action}
                    </span>
                    <span className="font-mono text-xs text-muted-foreground">{signal.bar}</span>
                    <span className="font-mono text-xs">{signal.price}</span>
                    <span className="text-muted-foreground">{signal.reason}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {signal.generated_at}
                    </span>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">暂无信号。</p>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>同一产品的其他形态</CardTitle>
              <CardDescription>
                两种形态的报价独立、价差单独列示，切换仅更换交易标的。
              </CardDescription>
            </CardHeader>
            <CardContent>
              {detail && detail.siblings.length > 0 ? (
                <ul className="divide-y">
                  {detail.siblings.map((sibling) => (
                    <li key={sibling.inst_id}>
                      <Link
                        to={`/watchlist/${sibling.inst_id}`}
                        className="flex flex-wrap items-center gap-3 py-3 text-sm underline-offset-4 hover:underline"
                      >
                        <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                          {instTypeLabel(sibling.inst_type)}
                        </span>
                        <span className="font-mono">{sibling.inst_id}</span>
                        <span className="ml-auto font-mono">{sibling.last_price}</span>
                        <span className={cn("font-mono text-xs", signedTone(sibling.price_spread_pct))}>
                          价差 {signedValue(sibling.price_spread_pct)}%
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">该产品暂无其他形态。</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="space-y-1.5">
                  <CardTitle>K 线</CardTitle>
                  <CardDescription>数据窗口以下方区间为准，缺口如实标注。</CardDescription>
                </div>
                <div className="flex flex-wrap gap-1" role="group" aria-label="K 线周期">
                  {BAR_OPTIONS.map((option) => (
                    <Button
                      key={option}
                      type="button"
                      size="sm"
                      variant={option === bar ? "default" : "outline"}
                      aria-pressed={option === bar}
                      onClick={() => setBar(option)}
                    >
                      {option}
                    </Button>
                  ))}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {seriesError ? (
                <p className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
                  {seriesError}
                </p>
              ) : null}

              {!seriesError && !series ? (
                <p className="py-10 text-center text-sm text-muted-foreground">加载中…</p>
              ) : null}

              {series ? (
                <>
                  <CandlestickChart candles={series.candles} />

                  <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="rounded-full border px-2 py-0.5">
                      数据源 {series.data_source}
                    </span>
                    <span className="rounded-full border px-2 py-0.5">周期 {series.bar}</span>
                    <span className="rounded-full border px-2 py-0.5">
                      {series.candles.length} 根
                    </span>
                    {series.available_from && series.available_to ? (
                      <span className="font-mono">
                        {series.available_from} ~ {series.available_to}
                      </span>
                    ) : null}
                    {series.has_gap ? (
                      <span className="rounded-full border border-amber-600/40 px-2 py-0.5 text-amber-600 dark:text-amber-400">
                        存在缺口
                      </span>
                    ) : null}
                  </div>

                  {lastCandle ? (
                    <dl className="mt-4 grid grid-cols-2 gap-3 border-t pt-4 text-xs sm:grid-cols-5">
                      <div className="grid gap-1">
                        <dt className="text-muted-foreground">开</dt>
                        <dd className="font-mono">{lastCandle.open}</dd>
                      </div>
                      <div className="grid gap-1">
                        <dt className="text-muted-foreground">高</dt>
                        <dd className="font-mono">{lastCandle.high}</dd>
                      </div>
                      <div className="grid gap-1">
                        <dt className="text-muted-foreground">低</dt>
                        <dd className="font-mono">{lastCandle.low}</dd>
                      </div>
                      <div className="grid gap-1">
                        <dt className="text-muted-foreground">收</dt>
                        <dd className="font-mono">{lastCandle.close}</dd>
                      </div>
                      <div className="grid gap-1">
                        <dt className="text-muted-foreground">
                          量{lastCandle.is_closed ? "" : "（未完成）"}
                        </dt>
                        <dd className="font-mono">{lastCandle.volume}</dd>
                      </div>
                    </dl>
                  ) : null}
                </>
              ) : null}
            </CardContent>
          </Card>
        </div>
      ) : null}
    </>
  );
}
