import { useEffect, useState } from "react";

import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type {
  BacktestCosts,
  BacktestDataSource,
  BacktestRequest,
  StrategyInstance,
} from "../../lib/api";

const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** 默认区间：最近 90 天。只影响输入框初值，不参与任何业务计算。 */
const DEFAULT_DAYS = 90;
const DAY_MS = 24 * 60 * 60 * 1000;

const DATA_SOURCES: Array<{ value: BacktestDataSource; label: string }> = [
  { value: "okx_spot", label: "OKX 现货（okx_spot）" },
  { value: "okx_swap", label: "OKX 永续（okx_swap）" },
  { value: "us_equity_proxy", label: "美股代理（us_equity_proxy，与实盘标的不可比）" },
  { value: "okx", label: "未区分形态的旧数据（okx）" },
];

const DEFAULT_COSTS: BacktestCosts = {
  maker_fee_bps: "2",
  taker_fee_bps: "5",
  slippage_bps: "3",
  spread_bps: "2",
};

function toDateInput(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function defaultDates(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end.getTime() - DEFAULT_DAYS * DAY_MS);
  return { start: toDateInput(start), end: toDateInput(end) };
}

export type BacktestFormProps = {
  instances: StrategyInstance[];
  instanceId: string | null;
  dataSource: BacktestDataSource;
  busy: boolean;
  onInstanceChange: (instanceId: string) => void;
  onDataSourceChange: (dataSource: BacktestDataSource) => void;
  onSubmit: (request: BacktestRequest) => void;
};

/**
 * 发起回测的表单：选实例 → 选标的集合 → 设成本与资金 → 跑。
 *
 * 表单只收集输入并原样提交：周期取自实例（回测周期必须与实例一致，后端会校验），
 * 其余数值不做任何换算。
 */
export function BacktestForm({
  instances,
  instanceId,
  dataSource,
  busy,
  onInstanceChange,
  onDataSourceChange,
  onSubmit,
}: BacktestFormProps) {
  const [dates, setDates] = useState(defaultDates);
  const [capital, setCapital] = useState("10000");
  const [positionSize, setPositionSize] = useState("2000");
  const [maxPositionPct, setMaxPositionPct] = useState("0.25");
  const [costs, setCosts] = useState<BacktestCosts>(DEFAULT_COSTS);
  const [selected, setSelected] = useState<string[]>([]);

  const instance = instances.find((item) => item.instance_id === instanceId) ?? null;

  useEffect(() => {
    setSelected(instance ? [...instance.inst_ids] : []);
  }, [instance]);

  const toggle = (instId: string) =>
    setSelected((current) =>
      current.includes(instId)
        ? current.filter((item) => item !== instId)
        : [...current, instId],
    );

  const submit = () => {
    if (!instance || selected.length === 0) return;
    onSubmit({
      strategy_instance_id: instance.instance_id,
      targets: {
        mode: selected.length === 1 ? "single" : "list",
        inst_ids: selected,
        group: null,
      },
      bar: instance.bar,
      start_date: dates.start,
      end_date: dates.end,
      initial_capital: capital,
      quote_currency: "USDT",
      position_size: positionSize,
      max_position_pct: maxPositionPct,
      costs,
      funding_enabled: true,
      execution_model: "next_open",
      data_source: dataSource,
    });
  };

  const costField = (key: keyof BacktestCosts, label: string) => (
    <label className="space-y-1.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <input
        className={INPUT_CLASS}
        value={costs[key]}
        onChange={(event) =>
          setCosts((current) => ({ ...current, [key]: event.target.value }))
        }
      />
    </label>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>发起回测</CardTitle>
        <CardDescription>
          选一个策略实例与它标的集合里的若干标的，每个标的各跑一条独立资金的回测；成本与
          资金假设随请求原样落库，结果可以按同一份请求重放。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1.5 text-sm">
            <span className="text-muted-foreground">策略实例</span>
            <select
              className={INPUT_CLASS}
              value={instanceId ?? ""}
              onChange={(event) => onInstanceChange(event.target.value)}
            >
              <option value="">请选择策略实例</option>
              {instances.map((item) => (
                <option key={item.instance_id} value={item.instance_id}>
                  {item.name}（{item.strategy_id} · {item.bar}）
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-muted-foreground">数据源</span>
            <select
              className={INPUT_CLASS}
              value={dataSource}
              onChange={(event) =>
                onDataSourceChange(event.target.value as BacktestDataSource)
              }
            >
              {DATA_SOURCES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {instance ? (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              标的集合（来自实例配置 · 周期 {instance.bar}）
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {instance.inst_ids.map((instId) => (
                <label
                  key={instId}
                  className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
                >
                  <input
                    type="checkbox"
                    checked={selected.includes(instId)}
                    onChange={() => toggle(instId)}
                  />
                  <span className="font-medium">{instId}</span>
                </label>
              ))}
            </div>
            {selected.length === 0 ? (
              <p className="text-xs text-muted-foreground">至少选择一个标的。</p>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            还没有可选的策略实例，先到「策略」页建一个。
          </p>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1.5 text-sm">
            <span className="text-muted-foreground">起始日期</span>
            <input
              type="date"
              className={INPUT_CLASS}
              value={dates.start}
              onChange={(event) =>
                setDates((current) => ({ ...current, start: event.target.value }))
              }
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-muted-foreground">结束日期</span>
            <input
              type="date"
              className={INPUT_CLASS}
              value={dates.end}
              onChange={(event) =>
                setDates((current) => ({ ...current, end: event.target.value }))
              }
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-muted-foreground">初始资金（计价货币 USDT）</span>
            <input
              className={INPUT_CLASS}
              value={capital}
              onChange={(event) => setCapital(event.target.value)}
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-muted-foreground">每笔交易金额</span>
            <input
              className={INPUT_CLASS}
              value={positionSize}
              onChange={(event) => setPositionSize(event.target.value)}
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-muted-foreground">最大持仓比例（0 到 1）</span>
            <input
              className={INPUT_CLASS}
              value={maxPositionPct}
              onChange={(event) => setMaxPositionPct(event.target.value)}
            />
          </label>
        </div>

        <div className="grid gap-3 sm:grid-cols-4">
          {costField("maker_fee_bps", "Maker 手续费（bps）")}
          {costField("taker_fee_bps", "Taker 手续费（bps）")}
          {costField("slippage_bps", "滑点（bps）")}
          {costField("spread_bps", "买卖价差（bps）")}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" onClick={submit} disabled={busy || !instance || selected.length === 0}>
            {busy ? "回测中…" : "跑回测"}
          </Button>
          <span className="text-xs text-muted-foreground">
            一次请求跑完所有选中的标的，每个标的一条结果。
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
