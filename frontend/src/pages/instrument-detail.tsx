import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { LineChart } from "../components/chart/line-chart";
import { PageHeading } from "../components/layout/page-parts";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import {
  fetchCandles,
  fetchIndicatorSeries,
  fetchInstrumentDetail,
  okxCandleSource,
  type CandleBar,
  type CandleSeriesResponse,
  type IndicatorParamValue,
  type IndicatorSeries,
  type IndicatorSeriesResponse,
  type InstrumentDetailResponse,
} from "../lib/api";
import { closePoints } from "../lib/chart";
import { instTypeLabel, signalTone, signedTone, signedValue } from "../lib/display";
import { coverageLabel, resolveDefaultBar } from "../lib/instrument";
import { cn } from "../lib/utils";

const BAR_OPTIONS: CandleBar[] = ["1m", "5m", "15m", "1h", "4h", "1d"];

/** 详情页展示的四张指标卡片；参数写在这里，卡片标题里的期数由此而来。 */
const INDICATOR_CARDS = [
  { name: "sma", title: "MA(20)", description: "简单移动平均，取最近 20 根收盘价。" },
  { name: "rsi", title: "RSI(14)", description: "相对强弱指标，取最近 14 根收盘价。" },
  { name: "macd", title: "MACD", description: "快线 12、慢线 26、信号线 9。" },
  { name: "atr", title: "ATR(14)", description: "平均真实波幅，取最近 14 根 K 线。" },
] as const;

const INDICATOR_NAMES: string[] = INDICATOR_CARDS.map((card) => card.name);

const INDICATOR_PARAMS: Record<string, Record<string, IndicatorParamValue>> = {
  sma: { period: 20 },
  rsi: { period: 14 },
  macd: { fast: 12, slow: 26, signal: 9 },
  atr: { period: 14 },
};

type IndicatorReading = { key: string; value: string; previous: string | null };

/**
 * 每个输出字段取最后两个有效值。
 *
 * 只用于显示当前值与方向，不在前端重算指标：数值原样来自接口。
 */
function readingsOf(series: IndicatorSeries | undefined): IndicatorReading[] {
  if (!series) return [];
  const keys: string[] = [];
  for (const point of series.points) {
    for (const key of Object.keys(point.values)) {
      if (!keys.includes(key)) keys.push(key);
    }
  }

  const readings: IndicatorReading[] = [];
  for (const key of keys) {
    let current: string | null = null;
    let previous: string | null = null;
    for (let index = series.points.length - 1; index >= 0; index -= 1) {
      const value = series.points[index].values[key] ?? null;
      if (value === null) continue;
      if (current === null) {
        current = value;
        continue;
      }
      previous = value;
      break;
    }
    if (current !== null) readings.push({ key, value: current, previous });
  }
  return readings;
}

type Direction = "up" | "down" | "flat" | null;

function directionOf(previous: string | null, value: string): Direction {
  if (previous === null) return null;
  const before = Number(previous);
  const now = Number(value);
  if (!Number.isFinite(before) || !Number.isFinite(now)) return null;
  if (now > before) return "up";
  if (now < before) return "down";
  return "flat";
}

function directionText(direction: Direction): string {
  if (direction === "up") return "↑ 比上一期上升";
  if (direction === "down") return "↓ 比上一期下降";
  if (direction === "flat") return "· 与上一期持平";
  return "上一期数值不足，无法比较";
}

function directionTone(direction: Direction): string {
  if (direction === "up") return "text-emerald-600 dark:text-emerald-400";
  if (direction === "down") return "text-rose-600 dark:text-rose-400";
  return "text-muted-foreground";
}

export default function InstrumentDetailPage() {
  const { instId = "" } = useParams<{ instId: string }>();
  const [detail, setDetail] = useState<InstrumentDetailResponse | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [bar, setBar] = useState<CandleBar | null>(null);
  const [candles, setCandles] = useState<CandleSeriesResponse | null>(null);
  const [candleError, setCandleError] = useState<string | null>(null);
  const [indicators, setIndicators] = useState<IndicatorSeriesResponse | null>(null);
  const [indicatorError, setIndicatorError] = useState<string | null>(null);

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
    const instType = detail?.instrument.inst_type;
    if (!instId || !instType) return;
    let active = true;
    setBar(null);
    setCandles(null);
    setCandleError(null);
    setIndicators(null);
    setIndicatorError(null);
    resolveDefaultBar((candidate) =>
      fetchCandles(instId, candidate, okxCandleSource(instType), 1),
    )
      .then((value) => {
        if (active) setBar(value);
      })
      .catch((reason: unknown) => {
        if (active) setCandleError(reason instanceof Error ? reason.message : "K 线加载失败");
      });
    return () => {
      active = false;
    };
  }, [instId, detail]);

  useEffect(() => {
    const instType = detail?.instrument.inst_type;
    if (!instId || !instType || !bar) return;
    let active = true;
    setCandles(null);
    setCandleError(null);
    fetchCandles(instId, bar, okxCandleSource(instType))
      .then((value) => {
        if (active) setCandles(value);
      })
      .catch((reason: unknown) => {
        if (active) setCandleError(reason instanceof Error ? reason.message : "K 线加载失败");
      });
    return () => {
      active = false;
    };
  }, [instId, bar, detail]);

  useEffect(() => {
    setIndicators(null);
    setIndicatorError(null);
    if (!instId || !bar) return;
    let active = true;
    fetchIndicatorSeries(instId, bar, INDICATOR_NAMES, INDICATOR_PARAMS)
      .then((value) => {
        if (active) setIndicators(value);
      })
      .catch((reason: unknown) => {
        if (active) setIndicatorError(reason instanceof Error ? reason.message : "指标加载失败");
      });
    return () => {
      active = false;
    };
  }, [instId, bar]);

  const instrument = detail?.instrument;
  const signal = detail?.latest_signal ?? null;
  const coverage = candles
    ? coverageLabel(candles.available_from, candles.available_to)
    : null;
  // 默认周期探测完成前禁用周期按钮，避免用户的选择被探测结果覆盖。
  const barLocked = bar === null && candleError === null;

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
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
      >
        ← 返回自选
      </Link>

      <PageHeading
        eyebrow="Instrument"
        title={instId}
        description="关键指标、收盘价走势与合约元数据；切换周期时折线和指标卡片一起刷新。"
      />

      {detailError ? (
        <p className="mb-6 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {detailError}
        </p>
      ) : null}

      {indicatorError ? (
        <p className="mb-6 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          指标加载失败：{indicatorError}
        </p>
      ) : null}

      <section className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="关键指标">
        {INDICATOR_CARDS.map((card) => {
          const series = indicators?.series.find((item) => item.name === card.name);
          const readings = readingsOf(series);
          return (
            <Card key={card.name}>
              <CardHeader className="pb-2">
                <CardTitle>{card.title}</CardTitle>
                <CardDescription>{card.description}</CardDescription>
              </CardHeader>
              <CardContent>
                {readings.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {indicators ? "暂无数据" : "加载中…"}
                  </p>
                ) : (
                  <dl className="grid gap-3">
                    {readings.map((reading) => {
                      const direction = directionOf(reading.previous, reading.value);
                      return (
                        <div key={reading.key} className="grid gap-0.5">
                          {readings.length > 1 ? (
                            <dt className="text-xs text-muted-foreground">{reading.key}</dt>
                          ) : null}
                          <dd className="font-mono text-xl tabular-nums">{reading.value}</dd>
                          <dd className={cn("text-xs", directionTone(direction))}>
                            {directionText(direction)}
                          </dd>
                        </div>
                      );
                    })}
                  </dl>
                )}
              </CardContent>
            </Card>
          );
        })}
      </section>

      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-1.5">
                <CardTitle>价格走势</CardTitle>
                <CardDescription>所选周期的收盘价连线；缺口如实标注。</CardDescription>
              </div>
              <div className="flex flex-wrap gap-1" role="group" aria-label="周期">
                {BAR_OPTIONS.map((option) => (
                  <Button
                    key={option}
                    type="button"
                    size="sm"
                    disabled={barLocked}
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
            {candleError ? (
              <p className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
                {candleError}
              </p>
            ) : null}

            {!candleError && !candles ? (
              <p className="py-10 text-center text-sm text-muted-foreground">加载中…</p>
            ) : null}

            {candles ? (
              <>
                {candles.candles.length > 0 ? (
                  <LineChart points={closePoints(candles.candles)} />
                ) : (
                  <p className="py-10 text-center text-sm text-muted-foreground">尚未同步行情</p>
                )}

                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="rounded-full border px-2 py-0.5">当前周期 {candles.bar}</span>
                  {coverage ? (
                    <span className="rounded-full border px-2 py-0.5">
                      覆盖区间 {coverage}
                    </span>
                  ) : null}
                  {candles.candles.length > 0 ? (
                    <>
                      <span className="rounded-full border px-2 py-0.5">
                        数据源 {candles.data_source}
                      </span>
                      <span className="rounded-full border px-2 py-0.5">
                        {candles.candles.length} 个收盘价
                      </span>
                      {candles.has_gap ? (
                        <span className="rounded-full border border-amber-600/40 px-2 py-0.5 text-amber-600 dark:text-amber-400">
                          存在缺口
                        </span>
                      ) : null}
                    </>
                  ) : null}
                </div>
              </>
            ) : null}
          </CardContent>
        </Card>

        {!detailError && !detail ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : null}

        {instrument ? (
          <>
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
                          <span
                            className={cn("font-mono text-xs", signedTone(sibling.price_spread_pct))}
                          >
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
          </>
        ) : null}
      </div>
    </>
  );
}
