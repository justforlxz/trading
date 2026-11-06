import type { EChartsOption } from "echarts";
import { useMemo } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import type { RelativeStrengthPayload } from "../../lib/api";
import { Chart, useChartTheme } from "./chart";
import {
  formatDecimal,
  formatMomentum,
  formatRatioPercent,
  formatTimestamp,
  trendLabel,
} from "./format";

const LOOKBACK_OPTIONS = [20, 40, 60, 120, 250];

type RelativeStrengthProps = {
  payload: RelativeStrengthPayload | null;
  loading: boolean;
  error: string | null;
  counterparty: string | null;
  lookback: number;
  onLookbackChange: (lookback: number) => void;
};

/**
 * 相对强弱：曲线与指标全部来自 `GET /targets/{id}/relative-strength`。
 * 窗口不足时后端返回 `defined: false` + 原因，这里原样展示，不用占位数据填充。
 */
export function RelativeStrength({
  payload,
  loading,
  error,
  counterparty,
  lookback,
  onLookbackChange,
}: RelativeStrengthProps) {
  const theme = useChartTheme();

  const option = useMemo<EChartsOption | null>(() => {
    if (!payload || !payload.defined || payload.series.length === 0) {
      return null;
    }
    return {
      grid: { left: 48, right: 16, top: 16, bottom: 32 },
      tooltip: {
        trigger: "axis",
        backgroundColor: theme.surface,
        borderColor: theme.border,
        textStyle: { color: theme.strongText, fontSize: 12 },
        valueFormatter: (value: unknown) =>
          typeof value === "number" ? value.toFixed(4) : String(value ?? "—"),
      },
      xAxis: {
        type: "category",
        data: payload.series.map((point) => point.ts),
        axisLabel: {
          color: theme.text,
          hideOverlap: true,
          formatter: (value: string) => value.slice(5, 10),
        },
        axisLine: { lineStyle: { color: theme.border } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: theme.text, formatter: (value: number) => value.toFixed(2) },
        splitLine: { lineStyle: { color: theme.border, opacity: 0.6 } },
      },
      series: [
        {
          type: "line",
          name: "RS 比值",
          smooth: true,
          showSymbol: false,
          data: payload.series.map((point) =>
            point.rs_ratio === null ? null : Number(point.rs_ratio),
          ),
          lineStyle: { width: 2, color: theme.positive },
          itemStyle: { color: theme.positive },
          areaStyle: { opacity: 0.08, color: theme.positive },
          markLine: {
            silent: true,
            symbol: "none",
            label: { show: false },
            data: [{ yAxis: 1 }],
            lineStyle: { color: theme.border, type: "dashed" },
          },
        },
      ],
    };
  }, [payload, theme]);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1.5">
            <CardTitle>相对强弱</CardTitle>
            <CardDescription>
              {counterparty
                ? `目标对 ${counterparty} 的比值曲线与区间超额收益。`
                : "选择一条关系边作为对手方后计算。"}
            </CardDescription>
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            回看
            <select
              value={lookback}
              onChange={(event) => onLookbackChange(Number(event.target.value))}
              className="h-8 rounded-md border bg-background px-2 text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {LOOKBACK_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value} 根
                </option>
              ))}
            </select>
          </label>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        {loading ? <p className="text-sm text-muted-foreground">计算中…</p> : null}

        {!loading && !error && !payload ? (
          <p className="text-sm text-muted-foreground">
            在上方相关性表中选择一行，或用网络图点选对手方。
          </p>
        ) : null}

        {payload && !payload.defined ? (
          <div className="rounded-lg border border-dashed p-4 text-sm leading-6 text-muted-foreground">
            相对强弱未定义：{payload.reason ?? "行情不足"}。
            <span className="ml-1">
              （口径 {payload.price_basis}，回看 {payload.lookback_bars} 根）
            </span>
          </div>
        ) : null}

        {payload && payload.defined ? (
          <>
            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div>
                <dt className="text-xs text-muted-foreground">RS 比值</dt>
                <dd className="mt-1 font-mono text-lg">{formatDecimal(payload.rs_ratio, 4)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">RS 动量</dt>
                <dd className="mt-1 font-mono text-lg">
                  {formatMomentum(payload.rs_momentum)}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">区间超额收益</dt>
                <dd className="mt-1 font-mono text-lg">
                  {formatRatioPercent(payload.excess_return)}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">趋势</dt>
                <dd className="mt-1 text-lg">{trendLabel(payload.trend)}</dd>
              </div>
            </dl>

            {option ? <Chart option={option} height={280} /> : null}

            <p className="text-xs leading-5 text-muted-foreground">
              口径 {payload.price_basis} · 回看 {payload.lookback_bars} 根 · 动量窗口{" "}
              {payload.momentum_bars} 根 · 截至 {formatTimestamp(payload.as_of)}
            </p>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
