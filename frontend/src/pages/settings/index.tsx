import { Monitor, Moon, Sun } from "lucide-react";
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
  type BacktestSettings,
  type CostSettings,
  type DataSettings,
  type ExecutionSettings,
  type RiskSettings,
  type SettingsResponse,
} from "../../lib/api";
import { useTheme, type ThemeMode } from "../../lib/theme";

const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

const BARS: Array<BacktestSettings["default_bar"]> = ["1m", "5m", "15m", "1h", "4h", "1d"];

const MODES: Array<{ value: ExecutionSettings["mode"]; label: string }> = [
  { value: "manual", label: "人工" },
  { value: "paper", label: "模拟" },
  { value: "live", label: "实盘" },
];

const THEME_OPTIONS: { mode: ThemeMode; label: string; icon: typeof Sun }[] = [
  { mode: "system", label: "跟随系统", icon: Monitor },
  { mode: "light", label: "浅色", icon: Sun },
  { mode: "dark", label: "深色", icon: Moon },
];

type Draft = {
  execution: ExecutionSettings;
  risk: RiskSettings;
  costs: CostSettings;
  backtest: BacktestSettings;
  data: DataSettings;
};

function toDraft(settings: SettingsResponse): Draft {
  return {
    execution: settings.execution,
    risk: settings.risk,
    costs: settings.costs,
    backtest: settings.backtest,
    data: settings.data,
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

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="space-y-1.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <input
        type="number"
        min={1}
        className={INPUT_CLASS}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
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

export default function SettingsPage() {
  const { mode, setMode } = useTheme();
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
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
    if (!draft || !settings) return;
    const switchingToLive =
      draft.execution.mode === "live" && settings.execution.mode !== "live";
    let acknowledged = false;
    if (switchingToLive) {
      acknowledged = window.confirm("切换到实盘会使用真实资金交易。确认继续？");
      if (!acknowledged) return;
    }

    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateSettings({
        execution: draft.execution,
        risk: draft.risk,
        costs: draft.costs,
        backtest: draft.backtest,
        data: draft.data,
        acknowledge_risk: acknowledged,
        exchange: apiKey.trim() ? { api_key: apiKey.trim() } : null,
      });
      setSettings(updated);
      setDraft(toDraft(updated));
      setApiKey("");
      setNotice("设置已保存");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
      try {
        const current = await fetchSettings();
        setSettings(current);
        setDraft(toDraft(current));
      } catch {
        // 保留原始错误；重新读取失败时界面仍显示上一次成功读取的值。
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeading
        eyebrow="Settings"
        title="设置"
        description="凭证与执行模式的唯一出口。API Key 只写不读，界面只显示是否已配置与掩码。"
      />

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <Button onClick={save} disabled={!draft || busy}>
          {busy ? "保存中…" : "保存设置"}
        </Button>
        {notice ? <span className="text-sm text-emerald-600 dark:text-emerald-400">{notice}</span> : null}
        {error ? <span className="text-sm text-destructive">{error}</span> : null}
      </div>

      {!draft || !settings ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : (
        <div className="grid gap-6">
          <Card>
            <CardHeader>
              <CardTitle>执行模式</CardTitle>
              <CardDescription>
                切到实盘会使用真实资金；保存前必须二次确认。自动交易默认关闭。
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1.5 text-sm">
                <span className="text-muted-foreground">模式</span>
                <select
                  className={INPUT_CLASS}
                  value={draft.execution.mode}
                  onChange={(event) =>
                    update("execution", {
                      mode: event.target.value as ExecutionSettings["mode"],
                    })
                  }
                >
                  {MODES.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}（{option.value}）
                    </option>
                  ))}
                </select>
              </label>
              <div className="grid gap-2">
                <CheckField
                  label="自动交易"
                  checked={draft.execution.auto_trading_enabled}
                  onChange={(checked) => update("execution", { auto_trading_enabled: checked })}
                />
                <CheckField
                  label="紧急停止"
                  checked={draft.execution.emergency_stop}
                  onChange={(checked) => update("execution", { emergency_stop: checked })}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>交易所凭证</CardTitle>
              <CardDescription>
                当前为{settings.exchange.demo_trading ? "模拟盘" : "实盘"}账户；API Key{" "}
                {settings.exchange.api_configured ? "已配置" : "未配置"}。Key 保存后只显示掩码，
                Secret 与 Passphrase 仍由环境变量注入。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <label className="space-y-1.5 text-sm">
                <span className="text-muted-foreground">API Key（留空不修改）</span>
                <input
                  type="password"
                  className={INPUT_CLASS}
                  value={apiKey}
                  placeholder={settings.exchange.api_configured ? "已配置，输入新值覆盖" : "未配置"}
                  onChange={(event) => setApiKey(event.target.value)}
                  autoComplete="off"
                />
              </label>
              <p className="text-xs text-muted-foreground">
                掩码：{settings.exchange.api_key_masked ?? "暂无"}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>风控限额</CardTitle>
              <CardDescription>杠杆硬上限为 10，不因这里的配置抬高。</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2">
              <TextField
                label="单笔最大金额"
                value={draft.risk.max_order_notional}
                onChange={(value) => update("risk", { max_order_notional: value })}
              />
              <TextField
                label="单标的最大持仓金额"
                value={draft.risk.max_position_notional}
                onChange={(value) => update("risk", { max_position_notional: value })}
              />
              <TextField
                label="总持仓资金限制"
                value={draft.risk.max_total_notional}
                onChange={(value) => update("risk", { max_total_notional: value })}
              />
              <NumberField
                label="最多持仓数量"
                value={draft.risk.max_positions}
                onChange={(value) => update("risk", { max_positions: value })}
              />
              <TextField
                label="杠杆上限（1–10）"
                value={draft.risk.max_leverage}
                onChange={(value) => update("risk", { max_leverage: value })}
              />
              <TextField
                label="单日最大亏损"
                value={draft.risk.max_daily_loss}
                onChange={(value) => update("risk", { max_daily_loss: value })}
              />
              <TextField
                label="强平缓冲（%）"
                value={draft.risk.liquidation_buffer_pct}
                onChange={(value) => update("risk", { liquidation_buffer_pct: value })}
              />
              <CheckField
                label="强制止损"
                checked={draft.risk.stop_loss_mandatory}
                onChange={(checked) => update("risk", { stop_loss_mandatory: checked })}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>交易成本</CardTitle>
              <CardDescription>回测与执行共用的成本假设，单位为基础点（bps）。</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2">
              <TextField
                label="Maker 手续费"
                value={draft.costs.maker_fee_bps}
                onChange={(value) => update("costs", { maker_fee_bps: value })}
              />
              <TextField
                label="Taker 手续费"
                value={draft.costs.taker_fee_bps}
                onChange={(value) => update("costs", { taker_fee_bps: value })}
              />
              <TextField
                label="滑点"
                value={draft.costs.slippage_bps}
                onChange={(value) => update("costs", { slippage_bps: value })}
              />
              <TextField
                label="买卖价差"
                value={draft.costs.spread_bps}
                onChange={(value) => update("costs", { spread_bps: value })}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>回测默认值</CardTitle>
              <CardDescription>只影响新建回测的初值，不改变历史结果。</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2">
              <TextField
                label="初始资金"
                value={draft.backtest.default_initial_capital}
                onChange={(value) => update("backtest", { default_initial_capital: value })}
              />
              <label className="space-y-1.5 text-sm">
                <span className="text-muted-foreground">默认周期</span>
                <select
                  className={INPUT_CLASS}
                  value={draft.backtest.default_bar}
                  onChange={(event) =>
                    update("backtest", {
                      default_bar: event.target.value as BacktestSettings["default_bar"],
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
              <CheckField
                label="计入资金费"
                checked={draft.backtest.funding_enabled}
                onChange={(checked) => update("backtest", { funding_enabled: checked })}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>数据源</CardTitle>
              <CardDescription>
                美股代理行情只用于补足历史窗口；代理配置状态为
                {draft.data.proxy_configured ? "已配置" : "未配置"}。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CheckField
                label="允许使用美股代理行情"
                checked={draft.data.proxy_enabled}
                onChange={(checked) => update("data", { proxy_enabled: checked })}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>外观</CardTitle>
              <CardDescription>
                默认跟随系统配色，手动选择后写入本地存储并在刷新后保持。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="inline-flex rounded-md border p-1" role="group" aria-label="主题模式">
                {THEME_OPTIONS.map((option) => {
                  const active = mode === option.mode;
                  return (
                    <Button
                      key={option.mode}
                      variant={active ? "secondary" : "ghost"}
                      size="sm"
                      aria-pressed={active}
                      onClick={() => setMode(option.mode)}
                      className="gap-2"
                    >
                      <option.icon className="h-4 w-4" aria-hidden="true" />
                      {option.label}
                    </Button>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
