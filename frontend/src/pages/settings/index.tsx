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
  updateSettings,
  type DisplaySettings,
  type ExecutionSettings,
  type RiskDefaults,
  type SettingsResponse,
} from "../../lib/api";
import { useTheme, type ThemeMode } from "../../lib/theme";
import { instrumentsToText, parseInstruments } from "../../lib/settings-draft";

const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

const BARS: Array<DisplaySettings["default_bar"]> = ["1m", "5m", "15m", "1h", "4h", "1d"];

const THEME_OPTIONS: { mode: ThemeMode; label: string }[] = [
  { mode: "system", label: "跟随系统" },
  { mode: "light", label: "浅色" },
  { mode: "dark", label: "深色" },
];

type Draft = {
  display: DisplaySettings;
  risk_defaults: RiskDefaults;
  execution: ExecutionSettings;
  // 订阅标的的输入原文由页面状态 `instrumentsText` 持有，草稿里只留 Provider 名。
  data_sources: { provider: string | null };
};

function toDraft(settings: SettingsResponse): Draft {
  return {
    display: settings.display,
    risk_defaults: settings.risk_defaults,
    execution: settings.execution,
    data_sources: {
      provider: settings.data_sources.provider ?? null,
    },
  };
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
      <input className={INPUT_CLASS} value={value} onChange={(event) => onChange(event.target.value)} />
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

export default function SettingsPage() {
  const { setMode } = useTheme();
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  // 订阅标的的输入原文与接口字段分开：逐项键入时逗号不能被解析结果覆盖。
  const [instrumentsText, setInstrumentsText] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchSettings()
      .then((value) => {
        if (!active) return;
        setSettings(value);
        setDraft(toDraft(value));
        setInstrumentsText(instrumentsToText(value.data_sources.subscribed_instruments ?? []));
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "设置加载失败");
      });
    return () => {
      active = false;
    };
  }, []);

  const update = <K extends keyof Draft>(group: K, patch: Partial<Draft[K]>) => {
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
      setDraft(toDraft(updated));
      setInstrumentsText(instrumentsToText(updated.data_sources.subscribed_instruments ?? []));
      setApiKey("");
      setNotice("设置已保存");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
      try {
        const current = await fetchSettings();
        setSettings(current);
        setDraft(toDraft(current));
        setInstrumentsText(instrumentsToText(current.data_sources.subscribed_instruments ?? []));
      } catch {
        // 读取失败时保留用户当前输入，只显示保存错误。
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeading
        eyebrow="设置"
        title="连接、显示与风险默认值"
        description="只保留数据连接、显示偏好、风险默认值和密钥状态；成本与回测默认值属于服务端内部参数。"
        actions={
          <>
            {notice ? (
              <span className="text-sm text-emerald-600 dark:text-emerald-400">{notice}</span>
            ) : null}
            {error ? <span className="text-sm text-destructive">{error}</span> : null}
            <Button onClick={save} disabled={!draft || busy}>
              {busy ? "保存中…" : "保存设置"}
            </Button>
          </>
        }
      />

      {!draft || !settings ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : (
        <div className="grid gap-6">
          <Card>
            <CardHeader>
              <CardTitle>数据连接</CardTitle>
              <CardDescription>
                外部数据源只决定适配器名称；最后同步时间与失败次数由服务端同步任务表提供。
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2">
              <TextField
                label="Provider"
                value={draft.data_sources.provider ?? ""}
                onChange={(value) => update("data_sources", { provider: value.trim() || null })}
              />
              <TextField
                label="订阅标的（逗号分隔）"
                value={instrumentsText}
                onChange={setInstrumentsText}
              />
              <p className="text-sm text-muted-foreground">
                最后同步：
                {settings.data_sources.last_sync_at ?? "暂无"}
              </p>
              <p className="text-sm text-muted-foreground">
                失败次数：{settings.data_sources.failure_count}
              </p>
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
                  onChange={(event) => {
                    const next = event.target.value as DisplaySettings["color_scheme"];
                    update("display", {
                      color_scheme: next,
                    });
                    // 同一个配色只保留一个入口：保存到后端的同时立刻套用到当前页面。
                    setMode(next);
                  }}
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
                    update("display", {
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
                  update("display", { price_precision: Number(value) || 0 })
                }
              />
              <TextField
                label="首页布局"
                value={draft.display.home_layout}
                onChange={(value) => update("display", { home_layout: value })}
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
                onChange={(value) => update("risk_defaults", { default_leverage: value })}
              />
              <TextField
                label="单笔风险预算"
                value={draft.risk_defaults.risk_budget_per_trade}
                onChange={(value) =>
                  update("risk_defaults", { risk_budget_per_trade: value })
                }
              />
              <TextField
                label="预警阈值（%）"
                value={draft.risk_defaults.warning_threshold}
                onChange={(value) => update("risk_defaults", { warning_threshold: value })}
              />
              <TextField
                label="止损规则"
                value={draft.risk_defaults.stop_rule}
                onChange={(value) => update("risk_defaults", { stop_rule: value })}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>自动执行</CardTitle>
              <CardDescription>
                自动交易开关默认关闭；保存它不会产生任何真实订单。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CheckField
                label="允许自动交易"
                checked={draft.execution.auto_trading_enabled}
                onChange={(checked) =>
                  update("execution", { auto_trading_enabled: checked })
                }
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>密钥状态</CardTitle>
              <CardDescription>
                API Key {settings.secrets.okx_configured ? "已配置" : "未配置"}。
                保存后只显示掩码，Secret 与 Passphrase 仍由环境变量注入。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <label className="space-y-1.5 text-sm">
                <span className="text-muted-foreground">API Key（留空不修改）</span>
                <input
                  type="password"
                  className={INPUT_CLASS}
                  value={apiKey}
                  placeholder={
                    settings.secrets.okx_configured ? "已配置，输入新值覆盖" : "未配置"
                  }
                  onChange={(event) => setApiKey(event.target.value)}
                  autoComplete="off"
                />
              </label>
              <p className="text-xs text-muted-foreground">
                掩码：{settings.secrets.okx_api_key_masked ?? "暂无"}
              </p>
            </CardContent>
          </Card>

        </div>
      )}
    </>
  );
}
