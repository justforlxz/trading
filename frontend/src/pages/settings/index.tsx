import { useEffect, useState } from "react";

import { PageHeading } from "../../components/layout/page-parts";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  fetchSettings,
  fetchSystemHealth,
  updateSettings,
  type DisplaySettings,
  type SettingsResponse,
  type SystemHealthResponse,
} from "../../lib/api";
import { formatBeijingTime } from "../../lib/display";
import {
  instrumentsToText,
  parseInstruments,
  toSettingsDraft,
  type SettingsDraft,
} from "../../lib/settings-draft";
import {
  apiKeyMaskedText,
  healthCheckedText,
  healthComponentLabel,
  healthStatusView,
  lastSuccessText,
  overallHealthLabel,
  parseSystemHealth,
  permissionLabel,
  sortHealthComponents,
} from "../../lib/system-health";
import { useTheme, type ThemeMode } from "../../lib/theme";
import { cn } from "../../lib/utils";

const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

const BARS: Array<DisplaySettings["default_bar"]> = ["1m", "5m", "15m", "1h", "4h", "1d"];

const THEME_OPTIONS: { mode: ThemeMode; label: string }[] = [
  { mode: "system", label: "跟随系统" },
  { mode: "light", label: "浅色" },
  { mode: "dark", label: "深色" },
];

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

function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="space-y-1.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <input
        className={INPUT_CLASS}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function CheckField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

function FactRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 border-b py-2 last:border-b-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="break-all font-mono text-sm tabular-nums">{value}</span>
    </div>
  );
}

function HealthBlock({
  health,
  loading,
  error,
  onRefresh,
}: {
  health: SystemHealthResponse | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}) {
  return (
    <div className="mt-5 border-t pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">系统健康</h3>
        <Button type="button" variant="outline" size="sm" onClick={onRefresh} disabled={loading}>
          {loading ? "刷新中…" : "刷新健康"}
        </Button>
      </div>
      {health === null ? (
        loading ? (
          <p className="mt-2 text-sm text-muted-foreground">正在读取系统健康…</p>
        ) : (
          <div className="mt-2 space-y-2">
            <ErrorNotice message={error ?? "系统健康不可用（后端未返回数据）"} />
            <Button type="button" variant="outline" size="sm" onClick={onRefresh}>
              重试
            </Button>
          </div>
        )
      ) : (
        <div className="mt-2 space-y-3">
          {error ? (
            <ErrorNotice message={`刷新失败，下面是上一次读取的结果：${error}`} />
          ) : null}
          <p className="text-sm text-muted-foreground">
            整体状态：{overallHealthLabel(health.status)}；检查时间：
            {healthCheckedText(health)}（北京时间）
          </p>
          <ul className="grid gap-2">
            {sortHealthComponents(health.components).map((component) => {
              const view = healthStatusView(component.status);
              return (
                <li
                  key={component.name}
                  className="min-w-0 rounded-md border px-3 py-2"
                  data-health-status={component.status}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      {healthComponentLabel(component.name)}
                    </span>
                    <span className={cn("rounded-full border px-2.5 py-0.5 text-xs", view.tone)}>
                      {view.label}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    最后成功时间：{lastSuccessText(component.last_success_at)}
                  </p>
                  {component.error ? (
                    <p className="mt-1 break-words text-xs text-destructive">
                      错误摘要：{component.error}
                    </p>
                  ) : null}
                  {component.detail ? (
                    <p className="mt-1 break-words text-xs text-muted-foreground">
                      详情：{component.detail}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

export type SettingsViewProps = {
  settings: SettingsResponse;
  draft: SettingsDraft;
  instrumentsText: string;
  apiKey: string;
  health: SystemHealthResponse | null;
  healthLoading: boolean;
  healthError: string | null;
  busy: boolean;
  error: string | null;
  notice: string | null;
  onDraftChange: <K extends keyof SettingsDraft>(
    group: K,
    patch: Partial<SettingsDraft[K]>,
  ) => void;
  onInstrumentsTextChange: (value: string) => void;
  onApiKeyChange: (value: string) => void;
  onColorSchemeChange: (value: DisplaySettings["color_scheme"]) => void;
  onSave: () => void;
  onRefreshHealth: () => void;
};

/** 纯展示组件：测试直接渲染它，不依赖网络与浏览器。 */
export function SettingsView({
  settings,
  draft,
  instrumentsText,
  apiKey,
  health,
  healthLoading,
  healthError,
  busy,
  error,
  notice,
  onDraftChange,
  onInstrumentsTextChange,
  onApiKeyChange,
  onColorSchemeChange,
  onSave,
  onRefreshHealth,
}: SettingsViewProps) {
  return (
    <>
      <PageHeading
        eyebrow="设置"
        title="连接、显示、风险默认值与密钥状态"
        description="数据连接与系统健康、显示偏好、风险默认值、自动执行开关和密钥状态；成本与回测默认值属于服务端内部参数，不在页面出现。"
        actions={
          <>
            {notice ? (
              <span className="text-sm text-emerald-600 dark:text-emerald-400">{notice}</span>
            ) : null}
            {error ? <span className="text-sm text-destructive">{error}</span> : null}
            <Button onClick={onSave} disabled={busy}>
              {busy ? "保存中…" : "保存设置"}
            </Button>
          </>
        }
      />

      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <CardTitle>数据连接</CardTitle>
            <CardDescription>
              Provider 与订阅标的写入设置文档；最后同步时间与失败次数由服务端同步任务表提供。
              系统健康只读后端已有的检查结果，页面不临时探测上游。
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            <TextField
              label="Provider"
              value={draft.data_sources.provider ?? ""}
              onChange={(value) =>
                onDraftChange("data_sources", { provider: value.trim() || null })
              }
            />
            <TextField
              label="订阅标的（逗号分隔）"
              value={instrumentsText}
              onChange={onInstrumentsTextChange}
            />
            <p className="text-sm text-muted-foreground">
              最后同步：
              {settings.data_sources.last_sync_at
                ? formatBeijingTime(settings.data_sources.last_sync_at)
                : "暂无"}
            </p>
            <p className="text-sm text-muted-foreground">
              失败次数：{settings.data_sources.failure_count}
            </p>
            <div className="sm:col-span-2">
              <HealthBlock
                health={health}
                loading={healthLoading}
                error={healthError}
                onRefresh={onRefreshHealth}
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>显示偏好</CardTitle>
            <CardDescription>默认周期与价格精度由后端保存，页面不自行换算。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1.5 text-sm">
              <span className="text-muted-foreground">配色</span>
              <select
                className={INPUT_CLASS}
                value={draft.display.color_scheme}
                onChange={(event) =>
                  onColorSchemeChange(event.target.value as DisplaySettings["color_scheme"])
                }
              >
                {THEME_OPTIONS.map((option) => (
                  <option key={option.mode} value={option.mode}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="text-muted-foreground">默认周期</span>
              <select
                className={INPUT_CLASS}
                value={draft.display.default_bar}
                onChange={(event) =>
                  onDraftChange("display", {
                    default_bar: event.target.value as DisplaySettings["default_bar"],
                  })
                }
              >
                {BARS.map((bar) => (
                  <option key={bar} value={bar}>
                    {bar}
                  </option>
                ))}
              </select>
            </label>
            <TextField
              label="价格精度"
              value={String(draft.display.price_precision)}
              onChange={(value) =>
                onDraftChange("display", { price_precision: Number(value) || 0 })
              }
            />
            <TextField
              label="首页布局"
              value={draft.display.home_layout}
              onChange={(value) => onDraftChange("display", { home_layout: value })}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>风险默认值</CardTitle>
            <CardDescription>策略新建时的默认参数，不是执行风控的硬上限。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            <TextField
              label="默认杠杆"
              value={draft.risk_defaults.default_leverage}
              onChange={(value) => onDraftChange("risk_defaults", { default_leverage: value })}
            />
            <TextField
              label="单笔风险预算"
              value={draft.risk_defaults.risk_budget_per_trade}
              onChange={(value) =>
                onDraftChange("risk_defaults", { risk_budget_per_trade: value })
              }
            />
            <TextField
              label="预警阈值（%）"
              value={draft.risk_defaults.warning_threshold}
              onChange={(value) => onDraftChange("risk_defaults", { warning_threshold: value })}
            />
            <TextField
              label="止损规则"
              value={draft.risk_defaults.stop_rule}
              onChange={(value) => onDraftChange("risk_defaults", { stop_rule: value })}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>自动执行</CardTitle>
            <CardDescription>
              规格第 3.8 节要求保留该开关：默认关闭，只保存状态，不产生任何真实订单。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CheckField
              label="允许自动交易"
              checked={draft.execution.auto_trading_enabled}
              onChange={(checked) =>
                onDraftChange("execution", { auto_trading_enabled: checked })
              }
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>密钥状态</CardTitle>
            <CardDescription>
              只展示掩码后的 API Key 与配置状态。Secret 与 Passphrase 由环境变量注入，
              接口不回显，页面也不读取。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-md border px-3 py-1">
              <FactRow label="API Key（掩码）" value={apiKeyMaskedText(settings.secrets)} />
              <FactRow
                label="配置状态"
                value={settings.secrets.okx_configured ? "已配置" : "未配置"}
              />
              <FactRow label="权限" value={permissionLabel(settings.secrets.okx_permission)} />
              <FactRow label="Secret" value="由环境变量注入，接口不返回是否设置" />
              <FactRow label="Passphrase" value="由环境变量注入，接口不返回是否设置" />
            </div>
            <label className="space-y-1.5 text-sm">
              <span className="text-muted-foreground">API Key（留空不修改）</span>
              <input
                type="password"
                className={INPUT_CLASS}
                value={apiKey}
                placeholder={
                  settings.secrets.okx_configured ? "已配置，输入新值覆盖" : "未配置"
                }
                onChange={(event) => onApiKeyChange(event.target.value)}
                autoComplete="off"
              />
            </label>
            <p className="text-xs text-muted-foreground">
              保存后接口只返回全掩码，明文不会读回。
            </p>
          </CardContent>
        </Card>
      </div>
    </>
  );
}

export default function SettingsPage() {
  const { setMode } = useTheme();
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  // 订阅标的的输入原文与接口字段分开：逐项键入时逗号不能被解析结果覆盖。
  const [instrumentsText, setInstrumentsText] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [health, setHealth] = useState<SystemHealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchSettings()
      .then((value) => {
        if (!active) return;
        setSettings(value);
        setDraft(toSettingsDraft(value));
        setInstrumentsText(instrumentsToText(value.data_sources.subscribed_instruments ?? []));
      })
      .catch((reason: unknown) => {
        if (active) setError(messageOf(reason, "设置加载失败"));
      });
    return () => {
      active = false;
    };
  }, []);

  const loadHealth = () => {
    setHealthLoading(true);
    setHealthError(null);
    fetchSystemHealth()
      .then((value) => setHealth(parseSystemHealth(value)))
      .catch((reason: unknown) => setHealthError(messageOf(reason, "系统健康读取失败")))
      .finally(() => setHealthLoading(false));
  };

  useEffect(() => {
    loadHealth();
  }, []);

  const update = <K extends keyof SettingsDraft>(
    group: K,
    patch: Partial<SettingsDraft[K]>,
  ) => {
    setDraft((current) =>
      current ? { ...current, [group]: { ...current[group], ...patch } } : current,
    );
  };

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateSettings({
        display: draft.display,
        risk_defaults: draft.risk_defaults,
        execution: draft.execution,
        data_sources: {
          provider: draft.data_sources.provider,
          subscribed_instruments: parseInstruments(instrumentsText),
        },
        exchange: apiKey.trim() ? { api_key: apiKey.trim() } : null,
      });
      setSettings(updated);
      setDraft(toSettingsDraft(updated));
      setInstrumentsText(instrumentsToText(updated.data_sources.subscribed_instruments ?? []));
      setApiKey("");
      setNotice("设置已保存");
    } catch (reason) {
      setError(messageOf(reason, "保存失败"));
      try {
        const current = await fetchSettings();
        setSettings(current);
        setDraft(toSettingsDraft(current));
        setInstrumentsText(instrumentsToText(current.data_sources.subscribed_instruments ?? []));
      } catch {
        // 读取失败时保留用户当前输入，只显示保存错误。
      }
    } finally {
      setBusy(false);
    }
  };

  if (!settings || !draft) {
    return (
      <>
        <PageHeading
          eyebrow="设置"
          title="连接、显示、风险默认值与密钥状态"
          description="数据连接与系统健康、显示偏好、风险默认值、自动执行开关和密钥状态。"
        />
        {error ? (
          <ErrorNotice message={error} />
        ) : (
          <p className="text-sm text-muted-foreground">加载中…</p>
        )}
      </>
    );
  }

  return (
    <SettingsView
      settings={settings}
      draft={draft}
      instrumentsText={instrumentsText}
      apiKey={apiKey}
      health={health}
      healthLoading={healthLoading}
      healthError={healthError}
      busy={busy}
      error={error}
      notice={notice}
      onDraftChange={update}
      onInstrumentsTextChange={setInstrumentsText}
      onApiKeyChange={setApiKey}
      onColorSchemeChange={(value) => {
        update("display", { color_scheme: value });
        // 同一个配色只保留一个入口：保存到后端的同时立刻套用到当前页面。
        setMode(value);
      }}
      onSave={save}
      onRefreshHealth={loadHealth}
    />
  );
}
