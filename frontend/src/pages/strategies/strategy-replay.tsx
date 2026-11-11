import { useEffect, useState } from "react";

import { LineChart } from "../../components/chart/line-chart";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  fetchStrategyReplays,
  replayStrategyInstance,
  type StrategyInstance,
  type StrategyReplay,
} from "../../lib/api";
import { instTypeLabel, signedTone, signedValue } from "../../lib/display";
import { cn } from "../../lib/utils";

const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** 回放表单的默认区间：最近 90 天。只影响输入框初值，不参与任何业务计算。 */
const DEFAULT_DAYS = 90;
const DAY_MS = 24 * 60 * 60 * 1000;

function toDateInput(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function defaultDates(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end.getTime() - DEFAULT_DAYS * DAY_MS);
  return { start: toDateInput(start), end: toDateInput(end) };
}

/** 日期输入 → UTC 时刻；结束日包含当天，因此取 23:59:59Z。 */
function toInstant(date: string, endOfDay: boolean): string {
  return `${date}T${endOfDay ? "23:59:59" : "00:00:00"}Z`;
}

function directionLabel(direction: StrategyReplay["target"]["legs"][number]["direction"]): string {
  return direction === "long" ? "多" : "空";
}

function shortHash(hash: string): string {
  return hash.length <= 16 ? hash : `${hash.slice(0, 16)}…`;
}

export type StrategyReplayPanelProps = {
  instance: StrategyInstance;
};

/**
 * 目标组合回放：选区间 → 回放 → 看卡片与折线。折线上只有一条净敞口曲线。
 *
 * 净值需要资金与成本假设，属于回测；这里展示的是目标组合本身的净敞口走势，
 * 以及它的规范化 JSON 与哈希（同一区间回放两次必须一致）。
 */
export function StrategyReplayPanel({ instance }: StrategyReplayPanelProps) {
  const [dates, setDates] = useState(defaultDates);
  const [replay, setReplay] = useState<StrategyReplay | null>(null);
  const [history, setHistory] = useState<StrategyReplay[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setReplay(null);
    setHistory([]);
    setError(null);
    fetchStrategyReplays(instance.instance_id)
      .then((value) => {
        if (active) setHistory(value.items);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "回放记录加载失败");
      });
    return () => {
      active = false;
    };
  }, [instance.instance_id]);

  const submit = () => {
    setBusy(true);
    setError(null);
    replayStrategyInstance(
      instance.instance_id,
      toInstant(dates.start, false),
      toInstant(dates.end, true),
    )
      .then((value) => {
        setReplay(value);
        return fetchStrategyReplays(instance.instance_id);
      })
      .then((value) => setHistory(value.items))
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "回放失败");
      })
      .finally(() => setBusy(false));
  };

  const seriesPoints =
    replay === null
      ? []
      : replay.points.map((point) => ({ time: point.as_of, price: point.net_exposure }));

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <div className="space-y-1.5">
            <CardTitle>目标组合回放</CardTitle>
            <CardDescription>
              实例 {instance.name}（{instance.instance_id}）按 {instance.bar} 周期在历史区间上重算目标组合；
              视图只用到该时点及之前的 K 线。停用的实例不能回放。
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="space-y-1.5 text-sm">
              <span className="text-muted-foreground">起始日期</span>
              <input
                type="date"
                className={INPUT_CLASS}
                value={dates.start}
                onChange={(event) => setDates((current) => ({ ...current, start: event.target.value }))}
              />
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="text-muted-foreground">结束日期</span>
              <input
                type="date"
                className={INPUT_CLASS}
                value={dates.end}
                onChange={(event) => setDates((current) => ({ ...current, end: event.target.value }))}
              />
            </label>
            <Button type="button" onClick={submit} disabled={busy || !instance.enabled}>
              {busy ? "回放中…" : "回放"}
            </Button>
            {!instance.enabled ? (
              <span className="text-xs text-muted-foreground">实例已停用，启用后才能回放。</span>
            ) : null}
          </div>

          {error ? (
            <p className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </CardContent>
      </Card>

      {replay ? (
        <>
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <CardTitle>目标组合</CardTitle>
                <span className="text-xs text-muted-foreground">
                  末点 {replay.points.at(-1)?.as_of ?? "—"}
                </span>
              </div>
              <CardDescription>
                目标权重之和为 1；净敞口是多头权重之和减空头权重之和。腿的数量与方向由模板决定。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {replay.target.legs.length === 0 ? (
                <p className="text-sm text-muted-foreground">该区间末端没有目标腿（信号不足或未通过筛选）。</p>
              ) : (
                <div className="grid gap-2">
                  {replay.target.legs.map((leg) => (
                    <div
                      key={leg.inst_id}
                      className="flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">{leg.inst_id}</span>
                        <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                          {instTypeLabel(leg.inst_type)}
                        </span>
                        <span
                          className={cn(
                            "rounded-full border px-2 py-0.5 text-xs",
                            leg.direction === "long"
                              ? "border-emerald-600/40 text-emerald-600 dark:text-emerald-400"
                              : "border-rose-600/40 text-rose-600 dark:text-rose-400",
                          )}
                        >
                          {directionLabel(leg.direction)}
                        </span>
                      </div>
                      <span className="font-mono text-sm tabular-nums">{leg.target_weight}</span>
                    </div>
                  ))}
                </div>
              )}

              <dl className="grid gap-3 border-t pt-3 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-xs text-muted-foreground">净敞口</dt>
                  <dd className={cn("font-mono tabular-nums", signedTone(replay.target.net_exposure))}>
                    {signedValue(replay.target.net_exposure)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">规范化哈希</dt>
                  <dd className="font-mono text-xs" title={replay.target_hash}>
                    {shortHash(replay.target_hash)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">区间 / 周期</dt>
                  <dd className="font-mono text-xs">
                    {replay.start} ~ {replay.end} · {replay.bar}
                  </dd>
                </div>
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="space-y-1.5">
                <CardTitle>净敞口走势</CardTitle>
                <CardDescription>
                  同一实例在该区间内逐点重算的目标组合净敞口；{replay.points.length} 个时点。
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <LineChart points={seriesPoints} label="净敞口走势" emptyText="该区间没有可回放的时点。" />
            </CardContent>
          </Card>
        </>
      ) : null}

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <CardTitle>回放记录</CardTitle>
            <span className="text-xs text-muted-foreground">{history.length} 条</span>
          </div>
          <CardDescription>
            每次回放都留一条执行记录；同一区间回放两次的规范化哈希必须相同。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {history.length === 0 ? (
            <p className="text-sm text-muted-foreground">还没有回放记录。</p>
          ) : (
            <div className="grid gap-2">
              {history.map((item) => (
                <div
                  key={item.replay_id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm"
                >
                  <span className="font-mono text-xs">
                    {item.start} ~ {item.end}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {item.target.legs.length} 条腿 · 净敞口{" "}
                    <span className={signedTone(item.target.net_exposure)}>
                      {signedValue(item.target.net_exposure)}
                    </span>
                  </span>
                  <span className="font-mono text-xs" title={item.target_hash}>
                    {shortHash(item.target_hash)}
                  </span>
                  <span className="text-xs text-muted-foreground">{item.created_at}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
