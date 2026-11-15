import { useEffect, useMemo, useState } from "react";

import { LineChart } from "../../components/chart/line-chart";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { BacktestReplayPoint, BacktestReplayResponse } from "../../lib/api";
import { replayClosePoints } from "../../lib/backtest-detail";
import { formatMoment } from "./format";
import { ReadingGrid, type Reading } from "./reading";

const SPEEDS = [0.5, 1, 2, 4] as const;
const FRAME_INTERVAL_MS = 700;

export type BacktestReplayPanelProps = {
  replay: BacktestReplayResponse | null;
  loading: boolean;
  error: string | null;
};

function pointReadings(point: BacktestReplayPoint): Reading[] {
  return [
    { label: "时刻", value: formatMoment(point.time) },
    { label: "收盘价", value: point.close ?? "—" },
    { label: "净值", value: point.equity, tone: true },
    { label: "现金", value: point.cash },
    { label: "持仓市值", value: point.position, tone: true },
    { label: "信号", value: point.signal },
    { label: "MA20", value: point.indicators.ma20 ?? "—" },
    { label: "MA60", value: point.indicators.ma60 ?? "—" },
  ];
}

/**
 * 历史回放：只在已保存的 `points` 数组里移动当前帧。
 *
 * 播放、暂停、单步、拖动进度与切换速度都不会发起请求，断开网络后仍可继续；
 * 页面不写入任何数据，也不访问实时行情。
 */
export function BacktestReplayPanel({ replay, loading, error }: BacktestReplayPanelProps) {
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(1);

  const lastFrame = Math.max(0, (replay?.points.length ?? 1) - 1);
  const point = replay?.points[Math.min(frame, lastFrame)] ?? null;

  useEffect(() => {
    setFrame(0);
    setPlaying(false);
  }, [replay]);

  useEffect(() => {
    if (!playing || replay === null) return;
    const timer = window.setInterval(() => {
      setFrame((current) => Math.min(current + 1, lastFrame));
    }, FRAME_INTERVAL_MS / speed);
    return () => window.clearInterval(timer);
  }, [playing, replay, speed, lastFrame]);

  useEffect(() => {
    if (playing && frame >= lastFrame) setPlaying(false);
  }, [playing, frame, lastFrame]);

  const closePoints = useMemo(
    () => (replay === null ? [] : replayClosePoints(replay.points, frame)),
    [replay, frame],
  );

  const frameEvents = (replay?.trades ?? []).filter((event) => event.index === frame);

  const togglePlay = () => {
    if (replay === null || replay.points.length === 0) return;
    if (!playing && frame >= lastFrame) setFrame(0);
    setPlaying((current) => !current);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>历史回放</CardTitle>
        <CardDescription>
          逐帧读取本次回测保存的净值、现金、持仓与信号；不请求实时行情，也不写入任何数据。
          {replay === null ? "" : ` 共 ${replay.points.length} 帧。`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {loading ? (
          <p className="py-10 text-center text-sm text-muted-foreground">正在读取回放序列…</p>
        ) : error !== null ? (
          <p className="py-10 text-center text-sm text-destructive">{error}</p>
        ) : replay === null || replay.points.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            这次回测没有保存可回放的序列。
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" size="sm" onClick={togglePlay}>
                {playing ? "暂停" : frame >= lastFrame ? "从头播放" : "播放"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setPlaying(false);
                  setFrame((current) => Math.max(0, current - 1));
                }}
                disabled={frame === 0}
              >
                上一帧
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setPlaying(false);
                  setFrame((current) => Math.min(lastFrame, current + 1));
                }}
                disabled={frame >= lastFrame}
              >
                下一帧
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  setPlaying(false);
                  setFrame(0);
                }}
                disabled={frame === 0}
              >
                回到起点
              </Button>
              <label className="ml-auto flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">速度</span>
                <select
                  className="h-8 rounded-md border border-input bg-transparent px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  value={speed}
                  onChange={(event) => setSpeed(Number(event.target.value))}
                >
                  {SPEEDS.map((value) => (
                    <option key={value} value={value}>
                      {value}x
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <label className="flex items-center gap-3 text-sm">
              <span className="whitespace-nowrap text-xs text-muted-foreground">
                第 {frame + 1} / {lastFrame + 1} 帧
              </span>
              <input
                type="range"
                min={0}
                max={lastFrame}
                step={1}
                value={frame}
                aria-label="回放进度"
                className="w-full accent-sky-500"
                onChange={(event) => {
                  setPlaying(false);
                  setFrame(Number(event.target.value));
                }}
              />
            </label>

            {point === null ? null : <ReadingGrid readings={pointReadings(point)} />}

            <div>
              <p className="mb-1 text-xs text-muted-foreground">收盘价（回放至当前帧）</p>
              <LineChart
                points={closePoints}
                label="回放收盘价"
                emptyText="当前帧之前没有收盘价。"
              />
            </div>

            <div className="text-xs text-muted-foreground">
              <span className="mr-2">当前帧成交</span>
              {frameEvents.length === 0 ? (
                <span>无</span>
              ) : (
                frameEvents.map((event) => (
                  <span key={`${event.trade_id}-${event.kind}`} className="mr-3 font-mono">
                    {event.kind === "entry" ? "入场" : "出场"} {event.side === "buy" ? "买入" : "卖出"}{" "}
                    {event.qty} @ {event.price}
                  </span>
                ))
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
