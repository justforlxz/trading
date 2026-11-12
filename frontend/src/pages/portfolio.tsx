import { useEffect, useMemo, useState } from "react";

import { PageHeading } from "../components/layout/page-parts";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import {
  createPortfolioAdjustment,
  decidePortfolioAdjustment,
  fetchPortfolioAdjustments,
  fetchPortfolioExposure,
  fetchStrategyPortfolio,
  fetchStrategyPortfolios,
  type ExposureOverviewResponse,
  type PortfolioAdjustment,
  type StrategyPortfolio,
  type StrategyPortfolioDetailResponse,
  type TargetPortfolio,
  type VirtualPosition,
} from "../lib/api";
import { signedTone, signedValue } from "../lib/display";
import { cn } from "../lib/utils";

const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";
const LABEL_CLASS = "space-y-1.5 text-sm";
const STATUS_LABELS: Record<PortfolioAdjustment["status"], string> = {
  pending: "待批准",
  approved: "已批准",
  rejected: "已驳回",
  superseded: "已被风险处置覆盖",
};
const WEIGHT_PATTERN = /^\d+(\.\d+)?$/;

type DraftLeg = {
  inst_id: string;
  inst_type: "SPOT" | "SWAP";
  direction: "long" | "short";
  target_weight: string;
};

const EMPTY_LEG: DraftLeg = {
  inst_id: "",
  inst_type: "SPOT",
  direction: "long",
  target_weight: "0.1",
};

function decimalPlaces(value: string): number {
  const dot = value.indexOf(".");
  return dot === -1 ? 0 : value.length - dot - 1;
}

function scaledDecimal(value: string, scale: number): bigint | null {
  const match = /^(-?)(\d*)(?:\.(\d*))?$/.exec(value.trim());
  if (!match) return null;
  const whole = match[2] ?? "";
  const fraction = match[3] ?? "";
  if (whole === "" && fraction === "") return null;
  const padded = fraction.padEnd(scale, "0").slice(0, scale);
  const magnitude = BigInt(`${whole || "0"}${padded}`);
  return match[1] === "-" ? -magnitude : magnitude;
}

/** 按十进制字符串求和，避免 0.1 + 0.2 的浮点尾差导致后端校验不通过。 */
function netWeight(legs: DraftLeg[]): string {
  const usable = legs.filter((leg) => WEIGHT_PATTERN.test(leg.target_weight.trim()));
  if (usable.length === 0) return "0";
  const scale = Math.min(12, Math.max(0, ...usable.map((leg) => decimalPlaces(leg.target_weight))));
  let total = 0n;
  for (const leg of usable) {
    const scaled = scaledDecimal(leg.target_weight, scale);
    if (scaled === null) continue;
    total += leg.direction === "long" ? scaled : -scaled;
  }
  const negative = total < 0n;
  const digits = (negative ? -total : total).toString().padStart(scale + 1, "0");
  const whole = digits.slice(0, digits.length - scale) || "0";
  const fraction = scale === 0 ? "" : `.${digits.slice(digits.length - scale)}`.replace(/\.?0+$/, "");
  return `${negative ? "-" : ""}${whole}${fraction}`;
}

function statusTone(status: PortfolioAdjustment["status"]): string {
  if (status === "approved") return "border-emerald-600/40 text-emerald-600 dark:text-emerald-400";
  if (status === "rejected") return "border-rose-600/40 text-rose-600 dark:text-rose-400";
  if (status === "superseded") return "border-slate-500/40 text-slate-600 dark:text-slate-300";
  return "border-amber-600/40 text-amber-600 dark:text-amber-400";
}

function directionLabel(direction: "long" | "short"): string {
  return direction === "long" ? "多头" : "空头";
}

/**
 * 各策略净敞口折线：横轴是策略，纵轴是名义价值。
 *
 * 只画一条线，不做蜡烛、成交量、多窗格或缩放；没有引入图表库。
 */
function StrategyExposureLine({ items }: { items: StrategyPortfolio[] }) {
  const points = items
    .map((item) => ({ label: item.name, value: Number(item.net_exposure) }))
    .filter((item) => Number.isFinite(item.value));
  if (points.length === 0) {
    return <p className="py-10 text-center text-sm text-muted-foreground">暂无策略敞口。</p>;
  }

  const width = 800;
  const height = 170;
  const left = 72;
  const right = width - 24;
  const top = 16;
  const bottom = height - 42;
  const low = Math.min(...points.map((point) => point.value));
  const high = Math.max(...points.map((point) => point.value));
  const span = high - low || Math.max(Math.abs(high) * 0.02, 1);
  const lowEdge = low - span * 0.1;
  const highEdge = high + span * 0.1;
  const slot = (right - left) / points.length;
  const xFor = (index: number) => left + slot * (index + 0.5);
  const yFor = (value: number) => top + ((highEdge - value) / (highEdge - lowEdge)) * (bottom - top);
  const line = points
    .map((point, index) => `${index === 0 ? "M" : "L"}${xFor(index)} ${yFor(point.value)}`)
    .join(" ");
  const labelStep = Math.max(1, Math.ceil(points.length / 6));
  const ticks = [highEdge, (highEdge + lowEdge) / 2, lowEdge];

  return (
    <svg
      className="w-full"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`各策略净敞口折线，共 ${points.length} 个策略`}
    >
      {ticks.map((tick) => (
        <g key={tick}>
          <line
            x1={left}
            x2={right}
            y1={yFor(tick)}
            y2={yFor(tick)}
            strokeDasharray="3 5"
            className="stroke-border"
          />
          <text
            x={left - 8}
            y={yFor(tick) + 4}
            textAnchor="end"
            className="fill-muted-foreground text-[11px]"
          >
            {tick.toFixed(2)}
          </text>
        </g>
      ))}
      <path
        d={line}
        fill="none"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="stroke-sky-500"
      />
      {points.map((point, index) => (
        <g key={`${point.label}-${index}`}>
          <circle cx={xFor(index)} cy={yFor(point.value)} r={2.5} className="fill-sky-500" />
          {index % labelStep === 0 ? (
            <text
              x={xFor(index)}
              y={height - 14}
              textAnchor="middle"
              className="fill-muted-foreground text-[11px]"
            >
              {point.label.length > 10 ? `${point.label.slice(0, 10)}…` : point.label}
            </text>
          ) : null}
        </g>
      ))}
    </svg>
  );
}

function PositionList({ positions }: { positions: VirtualPosition[] }) {
  if (positions.length === 0) {
    return <p className="text-sm text-muted-foreground">该策略当前没有虚拟持仓。</p>;
  }
  return (
    <div className="grid gap-2">
      {positions.map((position) => (
        <div
          key={position.inst_id}
          className="grid gap-2 rounded-md border px-3 py-2 text-sm sm:grid-cols-6"
        >
          <span className="font-medium">{position.product_key}</span>
          <span className={position.direction === "long" ? "text-emerald-600" : "text-rose-600"}>
            {directionLabel(position.direction)}
          </span>
          <span className="font-mono text-xs">数量 {position.qty}</span>
          <span className="font-mono text-xs">成本 {position.avg_cost}</span>
          <span className="font-mono text-xs">标记 {position.mark_price}</span>
          <span className={cn("font-mono text-xs", signedTone(position.unrealized_pnl))}>
            未实现 {signedValue(position.unrealized_pnl)}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function PortfolioPage() {
  const [exposure, setExposure] = useState<ExposureOverviewResponse | null>(null);
  const [portfolios, setPortfolios] = useState<StrategyPortfolio[]>([]);
  const [adjustments, setAdjustments] = useState<PortfolioAdjustment[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<StrategyPortfolioDetailResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formInstanceId, setFormInstanceId] = useState("");
  const [requestedBy, setRequestedBy] = useState("lxz");
  const [decidedBy, setDecidedBy] = useState("lxz");
  const [note, setNote] = useState("");
  const [legs, setLegs] = useState<DraftLeg[]>([{ ...EMPTY_LEG }]);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetchPortfolioExposure(),
      fetchStrategyPortfolios(),
      fetchPortfolioAdjustments(),
    ])
      .then(([overview, listing, decisionList]) => {
        if (!active) return;
        setExposure(overview);
        setPortfolios(listing.items);
        setAdjustments(decisionList.items);
        setSelectedId(listing.items[0]?.instance_id ?? null);
        setFormInstanceId(listing.items[0]?.instance_id ?? "");
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "组合数据加载失败");
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let active = true;
    fetchStrategyPortfolio(selectedId)
      .then((value) => {
        if (active) setDetail(value);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "策略组合明细加载失败");
      });
    return () => {
      active = false;
    };
  }, [selectedId]);

  const target = useMemo<TargetPortfolio>(
    () => ({
      legs: legs.map((leg) => ({
        inst_id: leg.inst_id.trim(),
        inst_type: leg.inst_type,
        direction: leg.direction,
        target_weight: leg.target_weight.trim() || "0",
      })),
      net_exposure: netWeight(legs),
    }),
    [legs],
  );

  const canSubmit =
    !busy &&
    formInstanceId !== "" &&
    requestedBy.trim() !== "" &&
    legs.length > 0 &&
    legs.every(
      (leg) => leg.inst_id.trim() !== "" && WEIGHT_PATTERN.test(leg.target_weight.trim()),
    );

  function updateLeg(index: number, patch: Partial<DraftLeg>) {
    setLegs((current) =>
      current.map((leg, position) => (position === index ? { ...leg, ...patch } : leg)),
    );
  }

  function submitAdjustment() {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    createPortfolioAdjustment({
      instance_id: formInstanceId,
      requested_by: requestedBy.trim(),
      target,
      note: note.trim() === "" ? null : note.trim(),
    })
      .then((created) => {
        setAdjustments((current) => [created, ...current]);
        setNote("");
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "调整申请提交失败");
      })
      .finally(() => setBusy(false));
  }

  function decide(adjustment: PortfolioAdjustment, decision: "approved" | "rejected") {
    if (busy || decidedBy.trim() === "") return;
    setBusy(true);
    setError(null);
    decidePortfolioAdjustment(adjustment.adjustment_id, {
      decision,
      decided_by: decidedBy.trim(),
    })
      .then((updated) => {
        setAdjustments((current) =>
          current.map((item) => (item.adjustment_id === updated.adjustment_id ? updated : item)),
        );
        if (decision === "approved") {
          fetchPortfolioExposure().then(setExposure).catch(() => undefined);
          fetchStrategyPortfolios()
            .then((listing) => setPortfolios(listing.items))
            .catch(() => undefined);
          if (selectedId === updated.instance_id) {
            fetchStrategyPortfolio(updated.instance_id)
              .then(setDetail)
              .catch(() => undefined);
          }
        }
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "调整决定失败");
      })
      .finally(() => setBusy(false));
  }

  return (
    <>
      <PageHeading
        eyebrow="Portfolio"
        title="组合"
        description="每个策略独立核算虚拟持仓、FIFO 成本与盈亏；全局一层汇总资金预算、总敞口、净敞口、集中度和多空冲突。账户实际持仓不在这里，也不与交易所对账。"
      />

      {error ? (
        <p className="mb-6 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <div className="grid gap-6">
        <div className="grid gap-4 sm:grid-cols-3">
          {[
            {
              title: "总敞口（权重）",
              value: exposure?.gross_exposure ?? "—",
              description: "各策略持仓名义价值除以自身资金预算后相加。",
            },
            {
              title: "净敞口（权重）",
              value: exposure ? signedValue(exposure.net_exposure) : "—",
              description: "多头权重之和减去空头权重之和。",
              tone: exposure ? signedTone(exposure.net_exposure) : undefined,
            },
            {
              title: "集中度",
              value: exposure?.largest_position_share ?? "—",
              description: "单一产品净名义价值占各策略资金预算总和的比例。",
            },
          ].map((item) => (
            <Card key={item.title}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {item.title}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className={cn("font-mono text-2xl tracking-tight", item.tone)}>{item.value}</p>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">{item.description}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        <Card>
          <CardHeader>
            <CardTitle>各策略净敞口</CardTitle>
            <CardDescription>
              单条折线，按策略名称排列；纵轴是名义价值，正负由多空方向决定。当前共
              {exposure?.open_positions ?? 0} 条持仓、{exposure?.product_count ?? 0} 个产品。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <StrategyExposureLine items={portfolios} />
          </CardContent>
        </Card>

        {exposure && exposure.conflicts.length > 0 ? (
          <Card>
            <CardHeader>
              <CardTitle>多空冲突</CardTitle>
              <CardDescription>同一产品被不同策略持有相反方向；两侧策略都列在这里。</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-2">
                {exposure.conflicts.map((conflict) => (
                  <div key={conflict.product_key} className="rounded-md border px-3 py-2 text-sm">
                    <span className="font-medium">{conflict.product_key}</span>
                    <span className="ml-3 text-xs text-emerald-600 dark:text-emerald-400">
                      多头：{conflict.long_instance_ids.join("、")}
                    </span>
                    <span className="ml-3 text-xs text-rose-600 dark:text-rose-400">
                      空头：{conflict.short_instance_ids.join("、")}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle>策略级虚拟持仓</CardTitle>
            <CardDescription>资金预算、优先级与盈亏都来自策略自己的账本。</CardDescription>
          </CardHeader>
          <CardContent>
            {portfolios.length === 0 ? (
              <p className="text-sm text-muted-foreground">还没有策略实例。</p>
            ) : (
              <div className="grid gap-3">
                {portfolios.map((item) => (
                  <button
                    key={item.instance_id}
                    type="button"
                    onClick={() => setSelectedId(item.instance_id)}
                    className={cn(
                      "grid w-full gap-2 rounded-lg border p-4 text-left transition-colors sm:grid-cols-6",
                      item.instance_id === selectedId && "border-primary bg-accent/40",
                    )}
                  >
                    <span className="sm:col-span-2">
                      <span className="block text-sm font-medium">{item.name}</span>
                      <span className="text-xs text-muted-foreground">
                        优先级 {item.priority} · 预算 {item.capital_budget}
                      </span>
                    </span>
                    <span className="font-mono text-xs">名义 {item.gross_exposure}</span>
                    <span className={cn("font-mono text-xs", signedTone(item.net_exposure))}>
                      净 {signedValue(item.net_exposure)}
                    </span>
                    <span className="font-mono text-xs">持仓 {item.open_positions}</span>
                    <span className="font-mono text-xs">已实现 {item.realized_pnl}</span>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {detail ? (
          <Card>
            <CardHeader>
              <CardTitle>{detail.portfolio.name} · 明细</CardTitle>
              <CardDescription>
                未实现盈亏按最近成交价计算；已平仓标的的已实现盈亏仍保留在策略账本里。
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4">
              <PositionList positions={detail.positions} />
              <div className="rounded-md border px-3 py-2 text-sm">
                <span className="text-muted-foreground">当前生效目标：</span>
                {detail.target ? (
                  <span className="ml-2 font-mono text-xs">
                    净敞口 {detail.target.net_exposure} ·{" "}
                    {detail.target.legs
                      .map(
                        (leg) =>
                          `${leg.inst_id} ${directionLabel(leg.direction)} ${leg.target_weight}`,
                      )
                      .join("；")}
                  </span>
                ) : (
                  <span className="ml-2 text-muted-foreground">尚无已批准的目标组合。</span>
                )}
              </div>
            </CardContent>
          </Card>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle>提交调整申请</CardTitle>
            <CardDescription>
              申请只落为「待批准」，不改变生效目标；批准后才写入分配并记录批准人与时间。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="grid gap-4"
              onSubmit={(event) => {
                event.preventDefault();
                submitAdjustment();
              }}
            >
              <div className="grid gap-4 sm:grid-cols-3">
                <label className={LABEL_CLASS}>
                  <span className="text-muted-foreground">策略</span>
                  <select
                    className={INPUT_CLASS}
                    value={formInstanceId}
                    onChange={(event) => setFormInstanceId(event.target.value)}
                    required
                  >
                    <option value="">选择策略</option>
                    {portfolios.map((item) => (
                      <option key={item.instance_id} value={item.instance_id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={LABEL_CLASS}>
                  <span className="text-muted-foreground">申请人</span>
                  <input
                    className={INPUT_CLASS}
                    value={requestedBy}
                    onChange={(event) => setRequestedBy(event.target.value)}
                    maxLength={128}
                    required
                  />
                </label>
                <label className={LABEL_CLASS}>
                  <span className="text-muted-foreground">说明</span>
                  <input
                    className={INPUT_CLASS}
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder="例如提高 BTC 目标权重"
                    maxLength={512}
                  />
                </label>
              </div>

              <div className="grid gap-2">
                {legs.map((leg, index) => (
                  <div key={index} className="grid items-end gap-2 sm:grid-cols-5">
                    <label className={LABEL_CLASS}>
                      <span className="text-muted-foreground">标的</span>
                      <input
                        className={INPUT_CLASS}
                        value={leg.inst_id}
                        onChange={(event) => updateLeg(index, { inst_id: event.target.value })}
                        placeholder="BTC-USDT"
                        required
                      />
                    </label>
                    <label className={LABEL_CLASS}>
                      <span className="text-muted-foreground">类别</span>
                      <select
                        className={INPUT_CLASS}
                        value={leg.inst_type}
                        onChange={(event) =>
                          updateLeg(index, { inst_type: event.target.value as "SPOT" | "SWAP" })
                        }
                      >
                        <option value="SPOT">SPOT</option>
                        <option value="SWAP">SWAP</option>
                      </select>
                    </label>
                    <label className={LABEL_CLASS}>
                      <span className="text-muted-foreground">方向</span>
                      <select
                        className={INPUT_CLASS}
                        value={leg.direction}
                        onChange={(event) =>
                          updateLeg(index, { direction: event.target.value as "long" | "short" })
                        }
                      >
                        <option value="long">多头</option>
                        <option value="short">空头</option>
                      </select>
                    </label>
                    <label className={LABEL_CLASS}>
                      <span className="text-muted-foreground">目标权重</span>
                      <input
                        className={INPUT_CLASS}
                        type="number"
                        min="0"
                        step="any"
                        value={leg.target_weight}
                        onChange={(event) => updateLeg(index, { target_weight: event.target.value })}
                        required
                      />
                    </label>
                    <Button
                      type="button"
                      variant="ghost"
                      className="text-destructive hover:text-destructive"
                      onClick={() => setLegs((current) => current.filter((_, i) => i !== index))}
                      disabled={legs.length === 1 || busy}
                    >
                      移除
                    </Button>
                  </div>
                ))}
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setLegs((current) => [...current, { ...EMPTY_LEG }])}
                  disabled={busy}
                >
                  增加一条腿
                </Button>
                <Button type="submit" disabled={!canSubmit}>
                  {busy ? "提交中…" : "提交申请"}
                </Button>
                <span className="text-xs text-muted-foreground">
                  申请净敞口：<span className="font-mono">{target.net_exposure}</span>
                </span>
                {legs.some((leg) => !WEIGHT_PATTERN.test(leg.target_weight.trim())) ? (
                  <span className="text-xs text-destructive">目标权重必须是非负十进制数。</span>
                ) : null}
              </div>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div className="space-y-1.5">
                <CardTitle>调整申请</CardTitle>
                <CardDescription>批准与驳回都必须由人工作出，并记录决定人。</CardDescription>
              </div>
              <label className={cn(LABEL_CLASS, "w-48")}>
                <span className="text-muted-foreground">决定人</span>
                <input
                  className={INPUT_CLASS}
                  value={decidedBy}
                  onChange={(event) => setDecidedBy(event.target.value)}
                  maxLength={128}
                />
              </label>
            </div>
          </CardHeader>
          <CardContent>
            {adjustments.length === 0 ? (
              <p className="text-sm text-muted-foreground">还没有调整申请。</p>
            ) : (
              <div className="grid gap-3">
                {adjustments.map((adjustment) => (
                  <div key={adjustment.adjustment_id} className="rounded-lg border p-4">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="text-sm font-medium">
                        {adjustment.instance_id} · 净敞口 {adjustment.target.net_exposure}
                      </span>
                      <span
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-xs",
                          statusTone(adjustment.status),
                        )}
                      >
                        {STATUS_LABELS[adjustment.status]}
                      </span>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      {adjustment.target.legs
                        .map(
                          (leg) =>
                            `${leg.inst_id} ${directionLabel(leg.direction)} ${leg.target_weight}`,
                        )
                        .join("；")}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      申请人 {adjustment.requested_by} · 申请于 {adjustment.requested_at}
                      {adjustment.decided_by
                        ? ` · 决定人 ${adjustment.decided_by} · 决定时间 ${adjustment.decided_at}`
                        : ""}
                    </p>
                    {adjustment.note ? (
                      <p className="mt-1 text-xs text-muted-foreground">说明：{adjustment.note}</p>
                    ) : null}
                    {adjustment.status === "pending" ? (
                      <div className="mt-3 flex gap-2">
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => decide(adjustment, "approved")}
                          disabled={busy || decidedBy.trim() === ""}
                        >
                          批准
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => decide(adjustment, "rejected")}
                          disabled={busy || decidedBy.trim() === ""}
                        >
                          驳回
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
