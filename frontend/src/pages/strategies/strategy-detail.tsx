import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type { StrategyDetail, StrategyVersionDetail } from "../../lib/api";
import { formatBeijingTime, signedTone, signedValue } from "../../lib/display";
import {
  categoryLabel,
  directionLabel,
  parameterRows,
  prettyJson,
  statusLabel,
  versionLabel,
} from "../../lib/strategies";
import { cn } from "../../lib/utils";

export type StrategyDetailPanelProps = {
  detail: StrategyDetail;
  versions: StrategyVersionDetail[];
  selectedVersionId: string | null;
  onSelectVersion: (versionId: string) => void;
  onEditMetadata: () => void;
  onNewVersion: () => void;
  onEditInstruments: () => void;
};

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  const text = prettyJson(value);
  return (
    <div className="space-y-1.5">
      <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h4>
      {text === "" ? (
        <p className="text-sm text-muted-foreground">未设置</p>
      ) : (
        <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-md border bg-muted/30 p-3 font-mono text-xs leading-5">
          {text}
        </pre>
      )}
    </div>
  );
}

/** 策略详情：版本目录与选中的版本。旧版本只读，调整标的只对当前版本开放。 */
export function StrategyDetailPanel({
  detail,
  versions,
  selectedVersionId,
  onSelectVersion,
  onEditMetadata,
  onNewVersion,
  onEditInstruments,
}: StrategyDetailPanelProps) {
  const selected =
    versions.find((version) => version.version_id === selectedVersionId) ?? versions[0] ?? null;
  const isCurrent = selected !== null && selected.version_id === detail.current_version_id;
  const latest = detail.latest_backtest;
  const parameters = selected === null ? [] : parameterRows(selected.parameters);

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle className="text-xl">{detail.name}</CardTitle>
              <CardDescription>
                {categoryLabel(detail.category)} · {statusLabel(detail.status)} · 当前{" "}
                {versionLabel(detail.current_version)} · {detail.instrument_ids.length} 个标的
              </CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm" onClick={onEditMetadata}>
                编辑元数据
              </Button>
              <Button type="button" size="sm" onClick={onNewVersion}>
                创建新版本
              </Button>
            </div>
          </div>
          {detail.description ? (
            <p className="text-sm leading-6 text-muted-foreground">{detail.description}</p>
          ) : null}
        </CardHeader>
        <CardContent className="grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
          <div>
            <p className="text-xs text-muted-foreground">策略标识</p>
            <p className="break-all font-mono text-xs">{detail.id}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">当前版本标识</p>
            <p className="break-all font-mono text-xs">{detail.current_version_id}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">更新时间</p>
            <p className="font-mono text-xs">{formatBeijingTime(detail.updated_at)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">最近回测</p>
            {latest ? (
              <p className="text-xs">
                {latest.backtest_start_date} ~ {latest.backtest_end_date} · {latest.trade_count} 笔 ·
                总收益率{" "}
                <span className={cn("font-mono", signedTone(latest.total_return_pct))}>
                  {signedValue(latest.total_return_pct)}%
                </span>{" "}
                · 最大回撤 <span className="font-mono">{latest.max_drawdown_pct}%</span>
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">还没有回测记录。</p>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <CardTitle>版本目录</CardTitle>
            <span className="text-xs text-muted-foreground">{versions.length} 个版本</span>
          </div>
          <CardDescription>版本是回测的可复现输入；旧版本不可修改。</CardDescription>
        </CardHeader>
        <CardContent>
          {versions.length === 0 ? (
            <p className="text-sm text-muted-foreground">没有版本。</p>
          ) : (
            <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {versions.map((version) => {
                const current = version.version_id === detail.current_version_id;
                return (
                  <li key={version.version_id}>
                    <button
                      type="button"
                      onClick={() => onSelectVersion(version.version_id)}
                      aria-current={version.version_id === selected?.version_id ? "true" : undefined}
                      className={cn(
                        "w-full rounded-lg border p-3 text-left transition-colors hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        version.version_id === selected?.version_id && "bg-accent/50 ring-2 ring-ring",
                      )}
                    >
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="text-sm font-medium">{versionLabel(version.version)}</span>
                        <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                          {current ? "当前版本" : "只读"}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {version.timeframe} · {directionLabel(version.direction)} ·{" "}
                        {formatBeijingTime(version.created_at)}
                      </p>
                      {version.change_note ? (
                        <p className="mt-1 break-words text-xs">{version.change_note}</p>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      {selected === null ? null : (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="space-y-1">
                <CardTitle>{versionLabel(selected.version)} 的可复现输入</CardTitle>
                <CardDescription>
                  {isCurrent
                    ? "当前版本可以在创建回测后继续调整标的集合。"
                    : "旧版本只读：规则、参数、仓位与标的都保持生成时的值。"}
                </CardDescription>
              </div>
              {isCurrent ? (
                <Button type="button" variant="outline" size="sm" onClick={onEditInstruments}>
                  调整标的
                </Button>
              ) : (
                <span className="rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground">
                  旧版本只读
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent className="grid gap-5">
            <div className="grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
              <div>
                <p className="text-xs text-muted-foreground">版本标识</p>
                <p className="break-all font-mono text-xs">{selected.version_id}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">周期</p>
                <p className="font-mono text-xs">{selected.timeframe}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">方向</p>
                <p className="text-xs">{directionLabel(selected.direction)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">创建时间</p>
                <p className="font-mono text-xs">{formatBeijingTime(selected.created_at)}</p>
              </div>
            </div>

            {selected.change_note ? (
              <p className="rounded-md border px-3 py-2 text-sm">
                <span className="text-muted-foreground">变更说明：</span>
                {selected.change_note}
              </p>
            ) : null}

            <JsonBlock title="规则 JSON" value={selected.rule_json} />

            <div className="space-y-1.5">
              <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                参数
              </h4>
              {parameters.length === 0 ? (
                <p className="text-sm text-muted-foreground">未设置参数。</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-xs text-muted-foreground">
                        <th className="py-2 pr-3 font-medium">参数</th>
                        <th className="py-2 font-medium">值</th>
                      </tr>
                    </thead>
                    <tbody>
                      {parameters.map((row) => (
                        <tr key={row.key} className="border-b last:border-b-0">
                          <td className="py-2 pr-3 font-mono text-xs">{row.key}</td>
                          <td className="break-all py-2 font-mono text-xs">{row.value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <JsonBlock title="仓位规则" value={selected.position_sizing} />
            <JsonBlock title="成本模型" value={selected.cost_model} />

            <div className="space-y-1.5">
              <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                标的集合
              </h4>
              {selected.instrument_ids.length === 0 ? (
                <p className="text-sm text-muted-foreground">尚未关联标的。</p>
              ) : (
                <ul className="flex flex-wrap gap-2">
                  {selected.instrument_ids.map((instId) => (
                    <li
                      key={instId}
                      className="rounded-full border px-2.5 py-0.5 font-mono text-xs"
                    >
                      {instId}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
