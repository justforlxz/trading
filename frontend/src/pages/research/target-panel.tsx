import { Loader2, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { CreateTargetInput, Exchange, Target } from "../../lib/api";
import { cn } from "../../lib/utils";

const EXCHANGES: Exchange[] = ["XNAS", "XNYS", "NYSE_ARCA"];

type TargetPanelProps = {
  targets: Target[];
  selectedId: number | null;
  loading: boolean;
  busy: boolean;
  error: string | null;
  onSelect: (targetId: number) => void;
  onCreate: (input: CreateTargetInput) => Promise<void>;
  onDelete: (target: Target) => Promise<void>;
};

export function TargetPanel({
  targets,
  selectedId,
  loading,
  busy,
  error,
  onSelect,
  onCreate,
  onDelete,
}: TargetPanelProps) {
  const [symbol, setSymbol] = useState("");
  const [exchange, setExchange] = useState<Exchange>("XNAS");
  const [displayName, setDisplayName] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = symbol.trim();
    if (!trimmed) {
      return;
    }
    await onCreate({
      symbol: trimmed.toUpperCase(),
      exchange,
      display_name: displayName.trim() ? displayName.trim() : null,
    });
    setSymbol("");
    setDisplayName("");
  }

  return (
    <Card className="lg:sticky lg:top-20">
      <CardHeader>
        <CardTitle>目标股票</CardTitle>
        <CardDescription>分析锚点，可软删除；软删除后不再出现在默认列表。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <form className="space-y-2" onSubmit={handleSubmit}>
          <div className="flex gap-2">
            <input
              aria-label="股票代码"
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
              placeholder="AAPL"
              className="h-9 w-full min-w-0 rounded-md border bg-background px-3 text-sm uppercase outline-none placeholder:normal-case placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
            />
            <select
              aria-label="交易所"
              value={exchange}
              onChange={(event) => setExchange(event.target.value as Exchange)}
              className="h-9 shrink-0 rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {EXCHANGES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <input
            aria-label="显示名称（可选）"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="显示名称（可选）"
            className="h-9 w-full rounded-md border bg-background px-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
          />
          <Button type="submit" size="sm" className="w-full" disabled={busy || !symbol.trim()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            添加目标
          </Button>
        </form>

        {error ? <p className="text-xs text-destructive">{error}</p> : null}

        <div className="border-t pt-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
            已启用
          </p>
          {loading ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </p>
          ) : targets.length === 0 ? (
            <p className="text-sm text-muted-foreground">还没有目标股票，先添加一个。</p>
          ) : (
            <ul className="space-y-1">
              {targets.map((target) => (
                <li key={target.id} className="group flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => onSelect(target.id)}
                    aria-current={target.id === selectedId ? "true" : undefined}
                    className={cn(
                      "flex min-w-0 flex-1 items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                      target.id === selectedId
                        ? "bg-accent font-medium text-accent-foreground"
                        : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                    )}
                  >
                    <span className="truncate">{target.symbol}</span>
                    <span className="ml-2 shrink-0 text-xs text-muted-foreground">
                      {target.exchange}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label={`删除 ${target.symbol}`}
                    title="软删除"
                    disabled={busy}
                    onClick={() => void onDelete(target)}
                    className="rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-accent hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100 disabled:pointer-events-none"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <p className="text-xs leading-5 text-muted-foreground">
          只有真实行情覆盖的标的才能算相关性。行情不足时后端会明确返回缺失原因，不会用模拟数据补足。
        </p>
      </CardContent>
    </Card>
  );
}
