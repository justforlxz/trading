import { AlertTriangle, Loader2, Send, Sparkles } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";

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
import type { AiCitation, AiQueryResponse } from "../../lib/api";

const EXAMPLES = [
  "当前市场时段和行情覆盖情况如何？",
  "现在风控敞口是多少",
  "现在风控是否允许增加敞口？",
  "当前策略的持仓情况如何？",
];

const REFUSAL_HINT = "只读助手不执行写操作：下单、改策略、改风控、审批或启动实盘都会被拒绝。";

type UiError = {
  code: string;
  message: string;
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function CitationList({ citations }: { citations: AiCitation[] }) {
  if (citations.length === 0) {
    return <p className="text-sm text-muted-foreground">本次回答没有可复核引用。</p>;
  }
  return (
    <ul className="divide-y rounded-md border">
      {citations.map((citation, index) => (
        <li key={`${citation.type}-${index}`} className="space-y-1 px-3 py-2 text-xs">
          <div className="flex items-center justify-between gap-3">
            <span className="font-medium">{citation.type}</span>
            <span className="truncate font-mono text-muted-foreground">{citation.source}</span>
          </div>
          <dl className="grid gap-x-6 gap-y-0.5 sm:grid-cols-2">
            {Object.entries(citation)
              .filter(([key]) => key !== "type" && key !== "source")
              .map(([key, value]) => (
                <div key={key} className="flex min-w-0 gap-2">
                  <dt className="shrink-0 text-muted-foreground">{key}</dt>
                  <dd className="truncate font-mono">{formatValue(value)}</dd>
                </div>
              ))}
          </dl>
        </li>
      ))}
    </ul>
  );
}

export default function AssistantPage() {
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<AiQueryResponse | null>(null);
  const [error, setError] = useState<UiError | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = question.trim();
    if (!text || pending) return;
    setPending(true);
    setError(null);
    setResult(null);
    try {
      const response = await api.askAssistant({ question: text });
      setResult(response);
    } catch (err) {
      if (err instanceof api.ApiError) {
        setError({ code: err.code, message: err.message });
      } else {
        setError({
          code: "unknown",
          message: err instanceof Error ? err.message : "未知错误",
        });
      }
    } finally {
      setPending(false);
    }
  }

  // 403（写操作被拒）与 200 answerable=false（未许可/未识别）走同一条拒答提示：
  // 两者都不含任何域数据，页面也不渲染引用。
  const refused = error?.code === "ai_write_forbidden" || result?.answerable === false;

  return (
    <div className="space-y-6">
      <PageHeading
        eyebrow="P4 · 分析助手"
        title="只读分析助手"
        description="用自然语言询问市场时段、股票关系、策略与回测、风控和持仓。回答只引用后端本次实际读取的数据；助手不参与交易决策，也不执行任何写操作。"
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            提问
          </CardTitle>
          <CardDescription>
            只读问答不会下单、改策略或改风控；写意图会被直接拒绝并记录审计。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form className="space-y-3" onSubmit={handleSubmit}>
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={3}
              maxLength={2000}
              placeholder="例如：现在风控敞口是多少"
              className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                {EXAMPLES.map((example) => (
                  <button
                    key={example}
                    type="button"
                    onClick={() => setQuestion(example)}
                    className="rounded-full border px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    {example}
                  </button>
                ))}
              </div>
              <Button type="submit" disabled={pending || question.trim().length === 0}>
                {pending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Send className="h-4 w-4" aria-hidden="true" />
                )}
                发送
              </Button>
            </div>
          </form>

          {error && !refused ? (
            <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400">
              <span className="font-mono text-xs">{error.code}</span>
              <span className="ml-2">{error.message}</span>
            </div>
          ) : null}

          {refused ? (
            <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                {result?.answer ?? REFUSAL_HINT}
                {result?.reason ? (
                  <span className="ml-2 font-mono text-xs">{result.reason}</span>
                ) : (
                  <span className="ml-2 font-mono text-xs">{error?.code}</span>
                )}
              </span>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {result && result.answerable !== false ? (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>回答</CardTitle>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                {result.intent ? (
                  <span className="rounded-full border px-2.5 py-0.5">意图 {result.intent}</span>
                ) : null}
                <span className="rounded-full border px-2.5 py-0.5 font-mono">
                  {result.model.provider}:{result.model.model}
                </span>
                {result.degraded ? (
                  <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-0.5 text-amber-700 dark:text-amber-300">
                    规则式兜底
                  </span>
                ) : null}
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="whitespace-pre-wrap text-sm leading-6">{result.answer}</p>
            {result.missing && result.missing.length > 0 ? (
              <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
                数据不足，缺失项：{result.missing.join("、")}
              </p>
            ) : null}
            <div className="space-y-2">
              <h4 className="text-sm font-medium">引用（{result.citations.length}）</h4>
              <CitationList citations={result.citations} />
            </div>
            <p className="text-xs text-muted-foreground">
              引用值来自后端本次读取，页面不改写也不重算指标；对话不持久化。
            </p>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
