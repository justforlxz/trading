import { useEffect, useState, type FormEvent } from "react";

import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { formatBeijingTime } from "../../lib/display";
import {
  buildRiskConfigPayload,
  fetchRiskExposure,
  hasRiskConfigInput,
  marginUsageBasisLabel,
  measureText,
  notionalText,
  percentText,
  positionSourceLabel,
  riskLevelView,
  riskRuleMeta,
  riskSideLabel,
  riskStatusLabel,
  ruleLevelView,
  savePositionRiskConfig,
  sectorLabel,
  textOrUnavailable,
  unavailableText,
  type RiskConfigFields,
  type RiskExposure,
  type RiskPosition,
  type RiskRule,
} from "../../lib/risk";
import { cn } from "../../lib/utils";

const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

const EMPTY_CONFIG_FIELDS: RiskConfigFields = {
  stopPx: "",
  riskBudget: "",
  warningThresholdPct: "",
};

function messageOf(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function ErrorNotice({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive"
    >
      {message}
    </p>
  );
}

function Metric({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="min-w-0 rounded-md border px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 break-words font-mono text-sm tabular-nums" title={value}>
        {value}
      </dd>
      {note ? <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{note}</p> : null}
    </div>
  );
}

function RiskLevelBadge({ level }: { level: string | null | undefined }) {
  const view = riskLevelView(level);
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">综合风险等级</span>
      <span
        className={cn("rounded-full border px-3 py-1 text-sm font-medium", view.tone)}
        title={view.available ? undefined : "后端未返回有效的风险等级"}
      >
        {view.label}
      </span>
    </div>
  );
}

function PortfolioCard({
  exposure,
  loading,
  onRefresh,
}: {
  exposure: RiskExposure;
  loading: boolean;
  onRefresh: () => void;
}) {
  const summary = exposure.summary;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1.5">
            <CardTitle>组合风险与敞口</CardTitle>
            <CardDescription>
              数值由后端风险接口计算；页面只展示，不重新计算杠杆、ATR
              距离、占比或风险等级。
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <RiskLevelBadge level={summary.risk_level} />
            <Button type="button" variant="outline" size="sm" onClick={onRefresh} disabled={loading}>
              {loading ? "刷新中…" : "刷新"}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>状态：{riskStatusLabel(exposure.status)}</span>
          <span>截至 {exposure.as_of ? formatBeijingTime(exposure.as_of) : unavailableText("后端未返回 as_of")}</span>
          <span>币种：{textOrUnavailable(summary.currency)}</span>
        </div>

        <dl className="grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
          <Metric
            label="多头名义价值"
            value={notionalText(summary.long_notional, summary.currency)}
          />
          <Metric
            label="空头名义价值"
            value={notionalText(summary.short_notional, summary.currency)}
          />
          <Metric
            label="净名义价值"
            value={notionalText(summary.net_notional, summary.currency)}
          />
          <Metric
            label="总名义价值"
            value={notionalText(summary.gross_notional, summary.currency)}
          />
          <Metric
            label="保证金使用率"
            value={percentText(summary.margin_usage_pct, "后端未返回保证金使用率")}
            note={`口径：${marginUsageBasisLabel(summary.margin_usage_basis)}`}
          />
        </dl>
      </CardContent>
    </Card>
  );
}

function SectorCard({ exposure }: { exposure: RiskExposure }) {
  const sectors = exposure.sectors;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>行业敞口</CardTitle>
        <CardDescription>
          按后端返回的标的行业字段汇总；页面不合并行业，也不补造分类。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {sectors.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {exposure.status === "empty"
              ? "暂无持仓，没有行业敞口。"
              : unavailableText("后端未返回行业敞口")}
          </p>
        ) : (
          <div className="min-w-0 overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">行业</th>
                  <th className="px-2 py-2 text-right font-medium">名义价值</th>
                  <th className="py-2 pl-2 text-right font-medium">占比</th>
                </tr>
              </thead>
              <tbody>
                {sectors.map((sector) => (
                  <tr key={sector.sector} className="border-b last:border-0">
                    <td className="py-2 pr-3">{sectorLabel(sector.sector)}</td>
                    <td className="px-2 py-2 text-right font-mono tabular-nums">
                      {notionalText(sector.notional, exposure.summary.currency)}
                    </td>
                    <td className="py-2 pl-2 text-right font-mono tabular-nums">
                      {percentText(sector.weight_pct, "后端未返回行业占比")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ruleObjectText(rule: RiskRule, positions: RiskPosition[]): string {
  if (rule.position_ref === null || rule.position_ref === undefined) return "组合";
  const position = positions.find((item) => item.position_ref === rule.position_ref);
  return position === undefined ? rule.position_ref : position.display_symbol;
}

function ruleValueText(rule: RiskRule): string {
  if (rule.value !== null && rule.value !== undefined && rule.value.trim() !== "") {
    return rule.value;
  }
  return rule.rule_id === "stop_missing"
    ? unavailableText("该规则不使用计算值")
    : unavailableText("后端未返回计算值");
}

function ruleThresholdText(rule: RiskRule): string {
  if (rule.threshold !== null && rule.threshold !== undefined && rule.threshold.trim() !== "") {
    return rule.threshold;
  }
  return rule.rule_id === "stop_missing"
    ? unavailableText("该规则不使用阈值")
    : unavailableText("后端未返回阈值");
}

function ruleInputsText(ruleId: string): string {
  const meta = riskRuleMeta(ruleId);
  return meta === null
    ? unavailableText("前端未登记该规则的输入字段")
    : meta.inputs.join("、");
}

function RulesCard({ exposure }: { exposure: RiskExposure }) {
  const rules = exposure.rules;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>风险规则结果</CardTitle>
        <CardDescription>
          每条结果都带规则 ID、计算值、阈值和参与计算的字段名；级别与综合等级均来自后端。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {rules.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {exposure.status === "empty"
              ? "暂无持仓，没有风险规则结果。"
              : "没有触发的风险规则。"}
          </p>
        ) : (
          <div className="min-w-0 overflow-x-auto">
            <table className="w-full min-w-[920px] text-left text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">规则</th>
                  <th className="px-2 py-2 font-medium">级别</th>
                  <th className="px-2 py-2 font-medium">对象</th>
                  <th className="px-2 py-2 text-right font-medium">计算值</th>
                  <th className="px-2 py-2 text-right font-medium">阈值</th>
                  <th className="py-2 pl-2 font-medium">参与计算的字段</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule, index) => {
                  const level = ruleLevelView(rule.level);
                  const meta = riskRuleMeta(rule.rule_id);
                  return (
                    <tr key={`${rule.rule_id}-${rule.position_ref ?? "portfolio"}-${index}`} className="border-b last:border-0">
                      <td className="py-3 pr-3">
                        <div className="font-medium">{meta === null ? "未登记的规则" : meta.label}</div>
                        <div className="font-mono text-xs text-muted-foreground">{rule.rule_id}</div>
                      </td>
                      <td className="px-2 py-3">
                        <span
                          className={cn("whitespace-nowrap rounded-full border px-2 py-0.5 text-xs", level.tone)}
                          title={level.available ? undefined : "后端未返回有效的规则级别"}
                        >
                          {level.label}
                        </span>
                      </td>
                      <td className="px-2 py-3">{ruleObjectText(rule, exposure.positions)}</td>
                      <td className="px-2 py-3 text-right font-mono tabular-nums">
                        {ruleValueText(rule)}
                      </td>
                      <td className="px-2 py-3 text-right font-mono tabular-nums">
                        {ruleThresholdText(rule)}
                      </td>
                      <td className="py-3 pl-2 font-mono text-xs text-muted-foreground">
                        {ruleInputsText(rule.rule_id)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const FLAG_LABELS: Record<string, string> = {
  no_market_data: "缺少标的规格或行情",
  atr_unavailable: "缺少 ATR",
  stop_missing: "未设置止损",
  stop_distance: "止损距离不足",
  high_leverage: "杠杆超过阈值",
  single_instrument_weight: "单标的占比超过阈值",
};

function flagText(flag: string): string {
  return FLAG_LABELS[flag] ?? flag;
}

function hasFlag(position: RiskPosition, flag: string): boolean {
  return Array.isArray(position.flags) && position.flags.includes(flag);
}

function positionNotionalReason(position: RiskPosition): string {
  if (hasFlag(position, "no_market_data")) return "缺少标的规格或行情";
  return "后端未返回名义价值";
}

function stopDistanceReason(position: RiskPosition): string {
  if (position.stop_px === null || position.stop_px === undefined || position.stop_px.trim() === "") {
    return "没有本地止损配置";
  }
  return "后端未返回止损距离";
}

function atrDistanceReason(position: RiskPosition): string {
  if (hasFlag(position, "no_market_data")) return "缺少标的规格或行情";
  if (hasFlag(position, "atr_unavailable")) return "缺少 ATR（日线已完成 K 线不足）";
  if (position.stop_px === null || position.stop_px === undefined || position.stop_px.trim() === "") {
    return "没有本地止损配置";
  }
  return "后端未返回 ATR 距离";
}

function PositionRiskConfigForm({
  positionRef,
  saving,
  onSave,
}: {
  positionRef: string;
  saving: boolean;
  onSave: (positionRef: string, fields: RiskConfigFields) => void;
}) {
  const [fields, setFields] = useState<RiskConfigFields>(EMPTY_CONFIG_FIELDS);

  const update = (patch: Partial<RiskConfigFields>) =>
    setFields((current) => ({ ...current, ...patch }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!hasRiskConfigInput(fields)) return;
    onSave(positionRef, fields);
  };

  return (
    <form className="mt-3 grid gap-3" onSubmit={submit}>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="space-y-1 text-xs">
          <span className="text-muted-foreground">止损价 stop_px</span>
          <input
            className={INPUT_CLASS}
            inputMode="decimal"
            value={fields.stopPx}
            onChange={(event) => update({ stopPx: event.target.value })}
            placeholder="留空表示不修改"
          />
        </label>
        <label className="space-y-1 text-xs">
          <span className="text-muted-foreground">风险预算 risk_budget</span>
          <input
            className={INPUT_CLASS}
            inputMode="decimal"
            value={fields.riskBudget}
            onChange={(event) => update({ riskBudget: event.target.value })}
            placeholder="留空表示不修改"
          />
        </label>
        <label className="space-y-1 text-xs">
          <span className="text-muted-foreground">预警阈值 warning_threshold_pct</span>
          <input
            className={INPUT_CLASS}
            inputMode="decimal"
            value={fields.warningThresholdPct}
            onChange={(event) => update({ warningThresholdPct: event.target.value })}
            placeholder="留空表示不修改"
          />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={saving || !hasRiskConfigInput(fields)}>
          {saving ? "保存中…" : "保存风险设置"}
        </Button>
        <span className="text-xs text-muted-foreground">
          只提交填写了的字段；留空表示不修改已保存值，数值合法性由后端校验。
          风险预算与预警阈值没有独立读取接口，页面不缓存这两个值。
        </span>
      </div>
    </form>
  );
}

function PositionRiskCard({
  position,
  currency,
  saving,
  onSave,
}: {
  position: RiskPosition;
  currency: string | null | undefined;
  saving: boolean;
  onSave: (positionRef: string, fields: RiskConfigFields) => void;
}) {
  return (
    <div className="min-w-0 rounded-md border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-mono text-sm font-medium">
            {textOrUnavailable(position.display_symbol, "后端未返回标的名称")}
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {textOrUnavailable(position.inst_id, "后端未返回标的标识")} ·{" "}
            {positionSourceLabel(position.source)}
          </div>
        </div>
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-xs font-medium",
            position.side === "short"
              ? "border-rose-600/40 text-rose-600 dark:text-rose-400"
              : "border-emerald-600/40 text-emerald-600 dark:text-emerald-400",
          )}
        >
          {riskSideLabel(position.side)}
        </span>
      </div>

      <dl className="mt-3 grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-3">
        <Metric
          label="名义价值"
          value={notionalText(position.notional, currency, positionNotionalReason(position))}
        />
        <Metric
          label="单标的占比"
          value={percentText(position.weight_pct, "后端未返回单标的占比")}
        />
        <Metric
          label="标记价"
          value={textOrUnavailable(position.mark_px, "后端未返回标记价")}
        />
        <Metric
          label="止损价"
          value={textOrUnavailable(position.stop_px, "没有本地止损配置")}
        />
        <Metric
          label="止损距离"
          value={percentText(position.stop_distance_pct, stopDistanceReason(position))}
        />
        <Metric
          label="ATR 距离"
          value={measureText(position.atr_distance, "ATR", atrDistanceReason(position))}
        />
        <Metric
          label="杠杆"
          value={textOrUnavailable(position.lever, "后端未返回杠杆")}
        />
      </dl>

      {Array.isArray(position.flags) && position.flags.length > 0 ? (
        <p className="mt-3 text-xs text-muted-foreground">
          后端标记：{position.flags.map(flagText).join("、")}
        </p>
      ) : null}

      <details className="mt-3 border-t pt-3">
        <summary className="cursor-pointer text-sm font-medium">风险设置</summary>
        <PositionRiskConfigForm positionRef={position.position_ref} saving={saving} onSave={onSave} />
      </details>
    </div>
  );
}

function PositionsCard({
  exposure,
  savingRef,
  onSaveConfig,
}: {
  exposure: RiskExposure;
  savingRef: string | null;
  onSaveConfig: (positionRef: string, fields: RiskConfigFields) => void;
}) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>持仓级风险</CardTitle>
        <CardDescription>
          每条持仓展示止损距离、ATR 距离、杠杆和单标的占比；缺失字段写“不可用”，不按 0 处理。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {exposure.positions.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无持仓。</p>
        ) : (
          <div className="grid min-w-0 gap-3 xl:grid-cols-2">
            {exposure.positions.map((position) => (
              <PositionRiskCard
                key={position.position_ref}
                position={position}
                currency={exposure.summary.currency}
                saving={savingRef === position.position_ref}
                onSave={onSaveConfig}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export type RiskSectionViewProps = {
  exposure: RiskExposure | null;
  loading: boolean;
  error: string | null;
  notice: string | null;
  saveError: string | null;
  savingRef: string | null;
  onRefresh: () => void;
  onRetry: () => void;
  onSaveConfig: (positionRef: string, fields: RiskConfigFields) => void;
};

/** 纯展示组件：测试直接渲染它，不依赖网络与浏览器。 */
export function RiskSectionView({
  exposure,
  loading,
  error,
  notice,
  saveError,
  savingRef,
  onRefresh,
  onRetry,
  onSaveConfig,
}: RiskSectionViewProps) {
  if (exposure === null) {
    if (loading) {
      return (
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">正在读取风险与敞口…</p>
          </CardContent>
        </Card>
      );
    }
    return (
      <Card>
        <CardContent className="space-y-3 pt-6">
          <ErrorNotice
            message={error ?? "风险与敞口不可用（后端未返回数据）"}
          />
          <Button type="button" variant="outline" onClick={onRetry}>
            重试
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <section className="grid min-w-0 gap-4" aria-label="风险与敞口">
      {error ? <ErrorNotice message={error} /> : null}
      {saveError ? <ErrorNotice message={saveError} /> : null}
      {notice ? (
        <p
          role="status"
          className="rounded-md border border-emerald-600/40 bg-emerald-500/5 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-400"
        >
          {notice}
        </p>
      ) : null}
      <PortfolioCard exposure={exposure} loading={loading} onRefresh={onRefresh} />
      <SectorCard exposure={exposure} />
      <RulesCard exposure={exposure} />
      <PositionsCard
        exposure={exposure}
        savingRef={savingRef}
        onSaveConfig={onSaveConfig}
      />
    </section>
  );
}

function savedFieldsText(saved: {
  stop_px?: string | null;
  risk_budget?: string | null;
  warning_threshold_pct?: string | null;
}): string {
  const parts: string[] = [];
  if (saved.stop_px !== null && saved.stop_px !== undefined) parts.push(`止损价 ${saved.stop_px}`);
  if (saved.risk_budget !== null && saved.risk_budget !== undefined) {
    parts.push(`风险预算 ${saved.risk_budget}`);
  }
  if (saved.warning_threshold_pct !== null && saved.warning_threshold_pct !== undefined) {
    parts.push(`预警阈值 ${saved.warning_threshold_pct}%`);
  }
  return parts.length === 0 ? "后端没有返回已保存字段" : parts.join("、");
}

export default function RiskSection() {
  const [exposure, setExposure] = useState<RiskExposure | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savingRef, setSavingRef] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setSaveError(null);
    setNotice(null);

    fetchRiskExposure()
      .then((next) => {
        if (active) setExposure(next);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setExposure(null);
        setError(`风险与敞口不可用：${messageOf(reason, "未知错误")}`);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [reloadToken]);

  const handleSave = async (positionRef: string, fields: RiskConfigFields) => {
    const payload = buildRiskConfigPayload(fields);
    if (Object.keys(payload).length === 0) return;

    setSavingRef(positionRef);
    setSaveError(null);
    setNotice(null);
    try {
      const saved = await savePositionRiskConfig(positionRef, payload);
      try {
        const next = await fetchRiskExposure();
        setExposure(next);
        setError(null);
        setNotice(`已保存 ${positionRef} 的风险配置：${savedFieldsText(saved)}。`);
      } catch (reason: unknown) {
        setExposure(null);
        setError(`风险与敞口不可用：${messageOf(reason, "保存后刷新失败")}`);
        setNotice(`已保存 ${positionRef} 的风险配置，但刷新风险数据失败。`);
      }
    } catch (reason: unknown) {
      setSaveError(`保存风险配置失败：${messageOf(reason, "未知错误")}`);
    } finally {
      setSavingRef(null);
    }
  };

  return (
    <RiskSectionView
      exposure={exposure}
      loading={loading}
      error={error}
      notice={notice}
      saveError={saveError}
      savingRef={savingRef}
      onRefresh={() => setReloadToken((token) => token + 1)}
      onRetry={() => setReloadToken((token) => token + 1)}
      onSaveConfig={(positionRef, fields) => void handleSave(positionRef, fields)}
    />
  );
}
