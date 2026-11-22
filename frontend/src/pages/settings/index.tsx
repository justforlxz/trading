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
  fetchNotificationDeliveries,
  fetchSettings,
  fetchSystemHealth,
  testNotificationChannel,
  updateSettings,
  type DeliveryItem,
  type DisplaySettings,
  type NotificationChannel,
  type SettingsResponse,
  type SystemHealthResponse,
} from "../../lib/api";
import { formatBeijingTime } from "../../lib/display";
import {
  currentPermissionState,
  notificationPermissionLabel,
  permissionState,
  type NotificationPermissionState,
} from "../../lib/notifications";
import {
  NOTIFICATION_CHANNELS,
  channelLabel,
  credentialText,
  instrumentsToText,
  macroPatch,
  notificationsPatch,
  parseInstruments,
  toSettingsDraft,
  VIX_MINUTE_PROVIDERS,
  withChannel,
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
  deliveries: DeliveryItem[];
  deliveriesLoading: boolean;
  deliveriesError: string | null;
  testingChannel: NotificationChannel | null;
  busy: boolean;
  error: string | null;
  notice: string | null;
  notificationPermission: NotificationPermissionState;
  onDraftChange: <K extends keyof SettingsDraft>(
    group: K,
    patch: Partial<SettingsDraft[K]>,
  ) => void;
  onInstrumentsTextChange: (value: string) => void;
  onApiKeyChange: (value: string) => void;
  onColorSchemeChange: (value: DisplaySettings["color_scheme"]) => void;
  onSave: () => void;
  onRefreshHealth: () => void;
  onRefreshDeliveries: () => void;
  onTestChannel: (channel: NotificationChannel) => void;
  onRequestNotificationPermission: () => void;
};

/**
 * 测试发送只读已保存的接收方（服务端每次投递现读设置表）：草稿与保存值不一致，
 * 或者还没有保存值（首次配置）时都要提示「先保存再测试」，别让人以为输入框里的值会生效。
 */
function needsSavedReceiverHint(draft: string, saved: string): boolean {
  return saved === "" || draft.trim() !== saved;
}

/** 纯展示组件：测试直接渲染它，不依赖网络与浏览器。 */
export function SettingsView({
  settings,
  draft,
  instrumentsText,
  apiKey,
  health,
  healthLoading,
  healthError,
  deliveries,
  deliveriesLoading,
  deliveriesError,
  testingChannel,
  busy,
  error,
  notice,
  notificationPermission,
  onDraftChange,
  onInstrumentsTextChange,
  onApiKeyChange,
  onColorSchemeChange,
  onSave,
  onRefreshHealth,
  onRefreshDeliveries,
  onTestChannel,
  onRequestNotificationPermission,
}: SettingsViewProps) {
  // 测试发送只读已保存的接收方，输入框里的草稿值不参与投递：两种情况都要提醒。
  // 一是草稿与保存值不一致（改了没保存），二是还没有保存值（首次配置）。
  const savedTelegramChatId = (settings.notifications.telegram?.chat_id ?? "").trim();
  const savedWebhookUrl = (settings.notifications.webhook?.url ?? "").trim();
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
              订阅标的写入设置文档；最后同步时间与失败次数由服务端 OKX 同步任务表提供。
              系统健康只读后端已有的检查结果，页面不临时探测上游。
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
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
            <label className="space-y-1.5 text-sm">
              <span className="text-muted-foreground">VIX 分钟级数据源</span>
              <select
                className={INPUT_CLASS}
                value={draft.macro.vixMinute}
                onChange={(event) =>
                  onDraftChange("macro", { vixMinute: event.target.value })
                }
              >
                {VIX_MINUTE_PROVIDERS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
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
            <CardTitle>通知</CardTitle>
            <CardDescription>
              三个通道各自投递、各自记一行台账。浏览器通知用浏览器内置的 Notification
              API；Telegram 与 Webhook 由服务端直接发出，页面关闭后仍然有效。
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <div className="rounded-md border px-3 py-1">
              <FactRow label="浏览器权限" value={notificationPermissionLabel(notificationPermission)} />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={onRequestNotificationPermission}
                disabled={notificationPermission === "granted"}
              >
                {notificationPermission === "granted" ? "已允许" : "开启浏览器通知"}
              </Button>
              <span className="text-xs text-muted-foreground">
                被拒绝后需要到浏览器的站点设置里手动改回允许。
              </span>
            </div>
            <div className="grid gap-2 sm:grid-cols-3">
              {NOTIFICATION_CHANNELS.map((channel) => (
                <CheckField
                  key={channel}
                  label={`${channelLabel(channel)} 通道`}
                  checked={draft.notifications.channels.includes(channel)}
                  onChange={(checked) =>
                    onDraftChange("notifications", {
                      channels: withChannel(draft.notifications.channels, channel, checked),
                    })
                  }
                />
              ))}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="grid gap-2 rounded-md border p-3">
                <h3 className="text-sm font-medium">Telegram</h3>
                <TextField
                  label="chat_id"
                  value={draft.notifications.telegramChatId}
                  onChange={(value) =>
                    onDraftChange("notifications", { telegramChatId: value })
                  }
                />
                <FactRow
                  label="Bot token"
                  value={`${credentialText(
                    settings.notifications.telegram?.token_configured ?? false,
                  )}（环境变量 TELEGRAM_BOT_TOKEN）`}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onTestChannel("telegram")}
                  disabled={testingChannel !== null}
                >
                  {testingChannel === "telegram" ? "发送中…" : "测试发送"}
                </Button>
                {needsSavedReceiverHint(draft.notifications.telegramChatId, savedTelegramChatId) ? (
                  <p className="text-xs text-muted-foreground">
                    测试发送只用已保存的 chat_id：填好后先保存，再测试发送；chat_id
                    由给 bot 发过消息后取得。
                  </p>
                ) : null}
              </div>
              <div className="grid gap-2 rounded-md border p-3">
                <h3 className="text-sm font-medium">Webhook</h3>
                <TextField
                  label="接收地址"
                  value={draft.notifications.webhookUrl}
                  onChange={(value) => onDraftChange("notifications", { webhookUrl: value })}
                />
                <FactRow
                  label="签名密钥"
                  value={`${credentialText(
                    settings.notifications.webhook?.secret_configured ?? false,
                  )}（环境变量 WEBHOOK_SIGNING_SECRET，未配置就不加签）`}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onTestChannel("webhook")}
                  disabled={testingChannel !== null}
                >
                  {testingChannel === "webhook" ? "发送中…" : "测试发送"}
                </Button>
                {needsSavedReceiverHint(draft.notifications.webhookUrl, savedWebhookUrl) ? (
                  <p className="text-xs text-muted-foreground">
                    测试发送只用已保存的接收地址：填好后先保存，再测试发送。
                  </p>
                ) : null}
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              保存后通道开关立即生效，不用重启进程；接收方留空表示未配置，投递会记一条
              「未配置」的失败。浏览器通知只在页面打开时有效（含后台标签页）。
            </p>
            <div className="border-t pt-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-medium">最近投递</h3>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={onRefreshDeliveries}
                  disabled={deliveriesLoading}
                >
                  {deliveriesLoading ? "刷新中…" : "刷新投递"}
                </Button>
              </div>
              {deliveriesError ? (
                <div className="mt-2">
                  <ErrorNotice message={deliveriesError} />
                </div>
              ) : null}
              {deliveries.length === 0 ? (
                <p className="mt-2 text-sm text-muted-foreground">
                  {deliveriesLoading ? "正在读取最近投递…" : "还没有投递记录。"}
                </p>
              ) : (
                <ul className="mt-2 grid gap-2">
                  {deliveries.map((item) => (
                    <li
                      key={item.id}
                      className="rounded-md border px-3 py-2 text-sm"
                      data-delivery-status={item.status}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs text-muted-foreground">
                          {formatBeijingTime(item.created_at)}（北京时间）
                        </span>
                        <span className="font-mono text-xs">
                          {channelLabel(item.channel)} ·{" "}
                          {item.status === "delivered" ? "成功" : "失败"}
                        </span>
                      </div>
                      {item.error ? (
                        <p className="mt-1 break-words text-xs text-destructive">
                          错误：{item.error}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
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
  const [deliveries, setDeliveries] = useState<DeliveryItem[]>([]);
  const [deliveriesLoading, setDeliveriesLoading] = useState(true);
  const [deliveriesError, setDeliveriesError] = useState<string | null>(null);
  const [testingChannel, setTestingChannel] = useState<NotificationChannel | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [notificationPermission, setNotificationPermission] =
    useState<NotificationPermissionState>("unsupported");

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

  const loadDeliveries = () => {
    setDeliveriesLoading(true);
    setDeliveriesError(null);
    fetchNotificationDeliveries()
      .then((value) => setDeliveries(value.items ?? []))
      .catch((reason: unknown) => setDeliveriesError(messageOf(reason, "最近投递读取失败")))
      .finally(() => setDeliveriesLoading(false));
  };

  useEffect(() => {
    loadHealth();
    loadDeliveries();
  }, []);

  const testChannel = async (channel: NotificationChannel) => {
    setTestingChannel(channel);
    setError(null);
    setNotice(null);
    try {
      const result = await testNotificationChannel(channel);
      if (result.status === "delivered") {
        setNotice(`${channelLabel(channel)} 测试消息已投递`);
      } else {
        setError(`${channelLabel(channel)} 测试发送失败：${result.error ?? "未返回原因"}`);
      }
    } catch (reason) {
      setError(messageOf(reason, "测试发送失败"));
    } finally {
      setTestingChannel(null);
      // 台账由服务端写入：测试完再读一次，页面不自己编造投递记录。
      loadDeliveries();
    }
  };

  // 权限状态只能问浏览器；不支持时显示「不支持」，不伪造 granted。
  useEffect(() => {
    setNotificationPermission(currentPermissionState());
  }, []);

  const requestNotificationPermission = () => {
    if (typeof window === "undefined" || !("Notification" in window)) {
      setNotificationPermission("unsupported");
      return;
    }
    // 必须在本函数（用户点击）的同步调用栈里申请，否则浏览器会直接拒绝。
    window.Notification.requestPermission()
      .then((value) => setNotificationPermission(permissionState(value)))
      .catch(() => setNotificationPermission(currentPermissionState()));
  };

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
          subscribed_instruments: parseInstruments(instrumentsText),
          ...(macroPatch(draft.macro) === null ? {} : { macro: macroPatch(draft.macro) }),
        },
        notifications: notificationsPatch(draft.notifications),
        exchange: apiKey.trim() ? { api_key: apiKey.trim() } : null,
      });
      setSettings(updated);
      setDraft(toSettingsDraft(updated));
      setInstrumentsText(instrumentsToText(updated.data_sources.subscribed_instruments ?? []));
      setApiKey("");
      setNotice("设置已保存");
      loadDeliveries();
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
      deliveries={deliveries}
      deliveriesLoading={deliveriesLoading}
      deliveriesError={deliveriesError}
      testingChannel={testingChannel}
      busy={busy}
      error={error}
      notice={notice}
      notificationPermission={notificationPermission}
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
      onRefreshDeliveries={loadDeliveries}
      onTestChannel={testChannel}
      onRequestNotificationPermission={requestNotificationPermission}
    />
  );
}
