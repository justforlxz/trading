import { Loader2, RefreshCw, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PageHeading } from "../../components/layout/page-parts";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import * as api from "../../lib/api";
import type {
  RiskEventItem,
  RiskFundingReport,
  RiskPolicy,
  RiskStatus,
  RiskThresholds,
} from "../../lib/api";
import { cn } from "../../lib/utils";

const THRESHOLD_LABELS: { key: keyof RiskThresholds; label: string }[] = [
  { key: "max_order_notional", label: "单笔上限" },
  { key: "max_leg_weight", label: "单腿权重上限" },
  { key: "max_leverage", label: "杠杆上限" },
  { key: "max_gross_exposure", label: "总敞口上限" },
  { key: "max_net_exposure", label: "净敞口上限" },
  { key: "max_instrument_weight", label: "单标的上限" },
  { key: "max_concentration", label: "集中度上限" },
  { key: "drawdown_warn", label: "回撤一级阈值" },
  { key: "drawdown_reduce", label: "回撤二级阈值" },
  { key: "drawdown_close", label: "回撤三级阈值" },
  { key: "funding_rate_threshold", label: "资金费率阈值" },
  { key: "min_depth_notional", label: "最小盘口深度" },
];

const KIND_LABELS: Record<string, string> = {
  limit_breach: "限额越界",
  drawdown: "回撤",
  funding: "资金费率",
  liquidity: "流动性",
};

const ACTION_LABELS: Record<string, string> = {
  none: "无动作",
  warn: "警告",
  reduce: "减仓",
  close: "平仓",
};

const SEVERITY_LABELS: Record<string, string> = {
  tier1: "一级",
  tier2: "二级",
  tier3: "三级",
};

function describe(error: unknown): string {
  if (error instanceof api.ApiError) {
    return `${error.code}：${error.message}`;
  }
  return error instanceof Error ? error.message : "未知错误";
}

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function Metric({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-mono text-sm">{value ?? "—"}</p>
    </div>
  );
}

export function RiskPage() {
  const [policy, setPolicy] = useState<RiskPolicy | null>(null);
  const [status, setStatus] = useState<RiskStatus | null>(null);
  const [events, setEvents] = useState<RiskEventItem[]>([]);
  const [funding, setFunding] = useState<RiskFundingReport | null>(null);
  const [strategyInput, setStrategyInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [evaluating, setEvaluating] = useState(false);

  const strategyId = (() => {
    const trimmed = strategyInput.trim();
    if (trimmed === "") return undefined;
    const parsed = Number(trimmed);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
  })();

  const load = useCallback(async () => {
    setPending(true);
    setError(null);
    try {
      const [policyData, statusData, eventPage] = await Promise.all([
        api.getRiskPolicy(strategyId),
        api.getRiskStatus(strategyId),
        api.listRiskEvents({ limit: 20 }),
      ]);
      setPolicy(policyData);
      setStatus(statusData);
      setEvents(eventPage.items);
      try {
        setFunding(await api.getRiskFunding());
      } catch {
        // 公开行情不可用时 fail-closed：资金费率卡片留空，不影响限额与事件展示。
        setFunding(null);
      }
    } catch (err) {
      setError(describe(err));
    } finally {
      setPending(false);
    }
  }, [strategyId]);

  useEffect(() => {
    void load();
  }, [load]);

  const onEvaluate = async () => {
    setEvaluating(true);
    setError(null);
    try {
      if (strategyId === undefined) {
        setError("请先填写策略 ID，再发起评估。");
        return;
      }
      const accepted = await api.evaluateRisk({ strategy_id: strategyId });
      await api.waitForJob(accepted.job_id);
      await load();
    } catch (err) {
      setError(describe(err));
    } finally {
      setEvaluating(false);
    }
  };

  const allowed = status?.allowed ?? false;

  return (
    <div className="space-y-6">
      <PageHeading
        eyebrow="风险管理"
        title="风控面板"
        description="策略级与全局组合两级风控：当前是否允许增加敞口、命中哪条限额、超限如何处置。所有数值来自风控 API，不在前端做派生计算。"
      />

      <div className="flex items-center gap-3">
        <Button variant="outline" onClick={() => void load()} disabled={pending}>
          {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
          刷新
        </Button>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          策略 ID
          <input
            className="w-24 rounded-md border bg-background px-2 py-1 font-mono text-sm"
            value={strategyInput}
            onChange={(event) => setStrategyInput(event.target.value)}
            placeholder="全局"
            inputMode="numeric"
          />
        </label>
        <Button onClick={() => void onEvaluate()} disabled={evaluating || strategyId === undefined}>
          {evaluating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ShieldAlert className="mr-2 h-4 w-4" />}
          重新评估
        </Button>
      </div>

      {error ? (
        <Card>
          <CardContent className="py-4 text-sm text-red-600 dark:text-red-400">{error}</CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>当前状态</CardTitle>
          <CardDescription>
            {status?.scope === "global" ? "全局组合" : `策略 ${status?.strategy_id ?? "—"}`} ·
            限额版本 {status?.policy_version ?? "—"} · 资本 {status?.capital ?? "—"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex flex-wrap items-center gap-3">
            <span
              className={cn(
                "rounded-full border px-3 py-1 text-sm font-medium",
                allowed
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                  : "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400",
              )}
            >
              {allowed ? "允许增加敞口" : "拒绝放行"}
            </span>
            <span className="text-sm text-muted-foreground">
              原因：{status?.reason ? (KIND_LABELS[status.reason] ?? status.reason) : "—"}
            </span>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="总敞口" value={status?.gross_exposure ?? null} />
            <Metric label="净敞口" value={status?.net_exposure ?? null} />
            <Metric label="杠杆" value={status?.leverage ?? null} />
            <Metric label="集中度" value={status?.concentration ?? null} />
            <Metric label="多头敞口" value={status?.long_exposure ?? null} />
            <Metric label="空头敞口" value={status?.short_exposure ?? null} />
          </div>

          {status && status.breaches.length > 0 ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">命中限额</p>
              <ul className="space-y-1">
                {status.breaches.map((breach) => (
                  <li key={`${breach.code}:${breach.field}`} className="font-mono text-sm text-red-600 dark:text-red-400">
                    {breach.code} · {breach.field} · 观测 {breach.observed} / 阈值{" "}
                    {breach.threshold}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {status && status.duplicates.length > 0 ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">跨策略重复持仓</p>
              <ul className="space-y-1">
                {status.duplicates.map((item) => (
                  <li key={`${item.instrument_id}:${item.side}`} className="font-mono text-sm text-muted-foreground">
                    标的 {item.instrument_id} · {item.side} · 策略{" "}
                    {item.strategy_ids.join(", ")}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {status && status.long_short_conflicts.length > 0 ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">多空冲突标的</p>
              <p className="font-mono text-sm text-muted-foreground">
                {status.long_short_conflicts.join(", ")}
              </p>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>限额快照</CardTitle>
          <CardDescription>
            版本 {policy?.version ?? "—"} · 更新于 {formatTimestamp(policy?.updated_at ?? null)} ·{" "}
            {policy?.updated_by ?? "—"}
            {policy?.note ? ` · ${policy.note}` : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {THRESHOLD_LABELS.map(({ key, label }) => (
              <Metric
                key={key}
                label={label}
                value={policy ? policy.thresholds[key] : null}
              />
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>最近风险事件</CardTitle>
          <CardDescription>按时间倒序，最多 20 条；同一评估键下的重复超限不会重复入账。</CardDescription>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无风险事件。</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="py-2 pr-4 font-medium">时间</th>
                    <th className="py-2 pr-4 font-medium">类型</th>
                    <th className="py-2 pr-4 font-medium">级别</th>
                    <th className="py-2 pr-4 font-medium">处置动作</th>
                    <th className="py-2 pr-4 font-medium">策略</th>
                    <th className="py-2 pr-4 font-medium">观测 / 阈值</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr key={event.id} className="border-b last:border-0">
                      <td className="py-2 pr-4 whitespace-nowrap">{formatTimestamp(event.created_at)}</td>
                      <td className="py-2 pr-4">{KIND_LABELS[event.kind] ?? event.kind}</td>
                      <td className="py-2 pr-4">{SEVERITY_LABELS[event.severity] ?? event.severity}</td>
                      <td className="py-2 pr-4 font-medium">
                        {ACTION_LABELS[event.action] ?? event.action}
                      </td>
                      <td className="py-2 pr-4">{event.strategy_id ?? "全局"}</td>
                      <td className="py-2 pr-4 font-mono text-xs">
                        {event.observed_value ?? "—"} / {event.threshold ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>资金费率与流动性</CardTitle>
          <CardDescription>公开行情观测，缺失即 fail-closed。</CardDescription>
        </CardHeader>
        <CardContent>
          {!funding || funding.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              暂无观测数据（公开行情不可用时按 fail-closed 处理，不影响限额与事件展示）。
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="py-2 pr-4 font-medium">合约</th>
                    <th className="py-2 pr-4 font-medium">资金费率</th>
                    <th className="py-2 pr-4 font-medium">下次结算</th>
                    <th className="py-2 pr-4 font-medium">买一 / 卖一</th>
                    <th className="py-2 pr-4 font-medium">买盘 / 卖盘深度</th>
                  </tr>
                </thead>
                <tbody>
                  {funding.items.map((item) => (
                    <tr key={item.inst_id} className="border-b last:border-0">
                      <td className="py-2 pr-4 font-mono">{item.inst_id}</td>
                      <td className="py-2 pr-4 font-mono">{item.funding_rate}</td>
                      <td className="py-2 pr-4">{formatTimestamp(item.next_funding_at)}</td>
                      <td className="py-2 pr-4 font-mono">
                        {item.best_bid} / {item.best_ask}
                      </td>
                      <td className="py-2 pr-4 font-mono">
                        {item.bid_depth} / {item.ask_depth}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default RiskPage;
