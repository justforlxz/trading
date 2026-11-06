import type { RelationChange, RelationEdge } from "../../lib/api";
import { cn } from "../../lib/utils";
import { formatDecimal, formatPValue, lagLabel } from "./format";

type CorrelationTableProps = {
  edges: RelationEdge[];
  selectedCounterparty: string | null;
  onSelect: (instId: string) => void;
};

export function CorrelationTable({
  edges,
  selectedCounterparty,
  onSelect,
}: CorrelationTableProps) {
  if (edges.length === 0) {
    return <p className="text-sm text-muted-foreground">暂无相关性数据。</p>;
  }

  return (
    <div className="-mx-6 overflow-x-auto px-6">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <thead>
          <tr className="border-b text-left text-xs uppercase tracking-[0.08em] text-muted-foreground">
            <th className="py-2 pr-4 font-medium">排名</th>
            <th className="py-2 pr-4 font-medium">对手方</th>
            <th className="py-2 pr-4 font-medium">系数</th>
            <th className="py-2 pr-4 font-medium">最佳滞后</th>
            <th className="py-2 pr-4 font-medium">稳定性</th>
            <th className="py-2 font-medium">p 值</th>
          </tr>
        </thead>
        <tbody>
          {edges.map((edge) => {
            const coefficient = Number(edge.coefficient);
            const active = edge.counterparty_inst_id === selectedCounterparty;
            return (
              <tr
                key={`${edge.counterparty_inst_id}-${edge.best_lag}`}
                onClick={() => onSelect(edge.counterparty_inst_id)}
                className={cn(
                  "cursor-pointer border-b border-border/60 transition-colors last:border-0 hover:bg-accent/60",
                  active && "bg-accent/80",
                )}
              >
                <td className="py-2 pr-4 font-mono text-muted-foreground">#{edge.rank}</td>
                <td className="py-2 pr-4">
                  <span className="font-medium">
                    {edge.counterparty.symbol ?? edge.counterparty_inst_id}
                  </span>
                  <span className="ml-2 font-mono text-xs text-muted-foreground">
                    {edge.counterparty_inst_id}
                  </span>
                </td>
                <td
                  className={cn(
                    "py-2 pr-4 font-mono",
                    coefficient >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-red-700 dark:text-red-400",
                  )}
                >
                  {formatDecimal(edge.coefficient)}
                </td>
                <td className="py-2 pr-4 text-muted-foreground">{lagLabel(edge.best_lag)}</td>
                <td className="py-2 pr-4 font-mono">{formatDecimal(edge.stability, 3)}</td>
                <td className="py-2 font-mono">{formatPValue(edge.p_value)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const KIND_LABELS: Record<RelationChange["kind"], string> = {
  added: "新增",
  removed: "消失",
  changed: "变化",
};

export function SignificantChanges({ changes }: { changes: RelationChange[] }) {
  if (changes.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        与上一快照相比没有超过阈值的显著变化。
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {changes.map((change) => (
        <li
          key={`${change.counterparty}-${change.kind}`}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-muted/50 px-3 py-2 text-sm"
        >
          <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
            {KIND_LABELS[change.kind]}
          </span>
          <span className="font-medium">{change.counterparty}</span>
          <span className="font-mono text-muted-foreground">
            {change.previous === null ? "—" : formatDecimal(String(change.previous))} →{" "}
            {change.current === null ? "—" : formatDecimal(String(change.current))}
          </span>
          {change.sign_flip ? (
            <span className="rounded-full border border-red-500/40 px-2 py-0.5 text-xs text-red-700 dark:text-red-400">
              符号翻转
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
