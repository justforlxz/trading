import { GraphChart, LineChart } from "echarts/charts";
import { GridComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import type { EChartsType } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import { useEffect, useMemo, useRef } from "react";

import { useTheme } from "../../lib/theme";
import { cn } from "../../lib/utils";

// 按需注册：图表类型与组件显式引入，避免整包 echarts 进入产物。
echarts.use([
  GraphChart,
  LineChart,
  GridComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
]);

export type ChartTheme = {
  text: string;
  strongText: string;
  border: string;
  surface: string;
  positive: string;
  negative: string;
};

function cssToken(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value ? `hsl(${value})` : fallback;
}

/**
 * ECharts 不读 CSS 变量，这里把设计 token 转成具体颜色。
 * 依赖 `resolved` 使主题切换后重新取色，图表跟随浅色/深色。
 */
export function useChartTheme(): ChartTheme {
  const { resolved } = useTheme();
  return useMemo(
    () => ({
      text: cssToken("--muted-foreground", "#6b7280"),
      strongText: cssToken("--foreground", "#111827"),
      border: cssToken("--border", "#e5e7eb"),
      surface: cssToken("--card", "#ffffff"),
      positive: resolved === "dark" ? "#34d399" : "#047857",
      negative: resolved === "dark" ? "#f87171" : "#b91c1c",
    }),
    [resolved],
  );
}

export type ChartClickParams = {
  dataType?: "node" | "edge";
  data?: unknown;
  name?: string;
  seriesIndex?: number;
  dataIndex?: number;
};

type ChartProps = {
  option: EChartsOption;
  height?: number;
  className?: string;
  onClick?: (params: ChartClickParams) => void;
};

/** 薄封装：初始化/销毁实例、随容器尺寸自适应、把 option 变更写回实例。 */
export function Chart({ option, height = 340, className, onClick }: ChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<EChartsType | null>(null);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) {
      return;
    }
    const chart = echarts.init(node);
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(node);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
  }, [option]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !onClick) {
      return;
    }
    const handler = (params: unknown) => onClick(params as ChartClickParams);
    chart.on("click", handler);
    return () => {
      chart.off("click", handler);
    };
  }, [onClick]);

  return <div ref={containerRef} className={cn("w-full", className)} style={{ height }} />;
}
