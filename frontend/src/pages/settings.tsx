import { KeyRound, Loader2, Monitor, Moon, Plus, Sun, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { PageHeading } from "../components/layout/page-parts";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import * as api from "../lib/api";
import type { McpClient, McpScope } from "../lib/api";
import { useTheme, type ThemeMode } from "../lib/theme";

const OPTIONS: { mode: ThemeMode; label: string; icon: typeof Sun }[] = [
  { mode: "system", label: "跟随系统", icon: Monitor },
  { mode: "light", label: "浅色", icon: Sun },
  { mode: "dark", label: "深色", icon: Moon },
];

const SCOPE_OPTIONS: { value: McpScope; hint: string }[] = [
  { value: "read", hint: "只读：行情、研究、机会、策略、回测、风控、执行查询" },
  { value: "operate", hint: "含受控操作；依然不能审批策略或直接下单" },
];

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

export default function SettingsPage() {
  const { mode, setMode } = useTheme();

  const [clients, setClients] = useState<McpClient[]>([]);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<McpScope[]>(["read"]);
  const [issuedToken, setIssuedToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await api.listMcpClients();
      setClients(page.items);
    } catch (err) {
      setError(describe(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function toggleScope(scope: McpScope) {
    setScopes((current) =>
      current.includes(scope) ? current.filter((item) => item !== scope) : [...current, scope],
    );
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (scopes.length === 0) {
      setError("至少选择一个 scope");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const created = await api.createMcpClient({ name: name.trim(), scopes });
      setIssuedToken(created.token);
      setName("");
      setScopes(["read"]);
      await load();
    } catch (err) {
      setError(describe(err));
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(clientId: number) {
    setError(null);
    try {
      await api.revokeMcpClient(clientId);
      await load();
    } catch (err) {
      setError(describe(err));
    }
  }

  return (
    <>
      <PageHeading
        eyebrow="Settings"
        title="设置"
        description="外观、MCP 客户端与系统参数。MCP 是给外部 Agent 的受控接口：服务端不做自然语言理解，只做鉴权、scope 与审计。"
      />

      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <CardTitle>外观</CardTitle>
            <CardDescription>
              默认跟随系统配色，手动选择后写入本地存储并在刷新后保持。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="inline-flex rounded-md border p-1" role="group" aria-label="主题模式">
              {OPTIONS.map((option) => {
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

        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-4">
              <CardTitle>MCP 客户端</CardTitle>
              <span className="shrink-0 rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground">
                P4
              </span>
            </div>
            <CardDescription>
              Token 只在创建时显示一次，服务端只存摘要；吊销后同一 token 立即失效。
              外部 Agent 通过 <code className="font-mono text-xs">POST /mcp</code> 接入。
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-6">
            <form className="grid gap-3" onSubmit={handleCreate}>
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                <label className="grid gap-1 text-sm">
                  <span className="text-muted-foreground">客户端名称</span>
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="例如 claude-desktop"
                    maxLength={100}
                    required
                    className="h-9 rounded-md border bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                </label>
                <div className="flex items-end">
                  <Button type="submit" size="sm" disabled={creating || name.trim() === ""}>
                    {creating ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Plus className="h-4 w-4" aria-hidden="true" />
                    )}
                    生成客户端
                  </Button>
                </div>
              </div>

              <fieldset className="grid gap-2">
                <legend className="text-sm text-muted-foreground">Scope</legend>
                {SCOPE_OPTIONS.map((option) => (
                  <label key={option.value} className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={scopes.includes(option.value)}
                      onChange={() => toggleScope(option.value)}
                    />
                    <span>
                      <span className="font-mono text-xs">{option.value}</span>
                      <span className="ml-2 text-muted-foreground">{option.hint}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
            </form>

            {issuedToken ? (
              <div className="grid gap-2 rounded-md border border-dashed p-3">
                <p className="flex items-center gap-2 text-sm font-medium">
                  <KeyRound className="h-4 w-4" aria-hidden="true" />
                  新 token（仅此一次，请立即保存）
                </p>
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 overflow-x-auto rounded bg-muted px-2 py-1.5 font-mono text-xs">
                    {issuedToken}
                  </code>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      void navigator.clipboard.writeText(issuedToken).catch(() => undefined);
                    }}
                  >
                    复制
                  </Button>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setIssuedToken(null)}>
                    已保存
                  </Button>
                </div>
              </div>
            ) : null}

            {error ? (
              <p className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            ) : null}

            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="py-2 font-medium">名称</th>
                    <th className="py-2 font-medium">Scope</th>
                    <th className="py-2 font-medium">创建时间</th>
                    <th className="py-2 font-medium">最近调用</th>
                    <th className="py-2 font-medium">状态</th>
                    <th className="py-2 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {clients.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="py-6 text-center text-muted-foreground">
                        {loading ? "读取中…" : "还没有 MCP 客户端"}
                      </td>
                    </tr>
                  ) : (
                    clients.map((client) => (
                      <tr key={client.id} className="border-b last:border-0">
                        <td className="py-2 pr-3">{client.name}</td>
                        <td className="py-2 pr-3 font-mono text-xs">
                          {client.scopes.join(", ") || "—"}
                        </td>
                        <td className="py-2 pr-3 text-muted-foreground">
                          {formatTimestamp(client.created_at)}
                        </td>
                        <td className="py-2 pr-3 text-muted-foreground">
                          {formatTimestamp(client.last_used_at)}
                        </td>
                        <td className="py-2 pr-3">
                          <span
                            className={
                              client.revoked
                                ? "rounded-full border px-2 py-0.5 text-xs text-muted-foreground"
                                : "rounded-full border border-emerald-500/40 px-2 py-0.5 text-xs text-emerald-600 dark:text-emerald-400"
                            }
                          >
                            {client.revoked ? "已吊销" : "启用"}
                          </span>
                        </td>
                        <td className="py-2 text-right">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            disabled={client.revoked}
                            onClick={() => void handleRevoke(client.id)}
                            className="gap-1.5"
                          >
                            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                            吊销
                          </Button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-4">
              <CardTitle>行情源与系统参数</CardTitle>
              <span className="shrink-0 rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground">
                S3
              </span>
            </div>
            <CardDescription>
              S3 起接入：数据来源台账、同步状态与采集参数；密钥只经环境变量注入，不落库、不入前端。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-x-8 gap-y-2 text-sm text-muted-foreground sm:grid-cols-2">
              {["行情源与可回溯范围", "数据来源与抓取时间", "OKX 连接配置", "采集与保留策略"].map(
                (item) => (
                  <li key={item} className="flex items-start gap-2">
                    <span
                      className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/70"
                      aria-hidden="true"
                    />
                    {item}
                  </li>
                ),
              )}
            </ul>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
