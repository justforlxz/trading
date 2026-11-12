import { useEffect, useState } from "react";

import { LineChart } from "../../components/chart/line-chart";
import { PageHeading } from "../../components/layout/page-parts";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  fetchJournal,
  type JournalEntry,
  type JournalFill,
  type JournalOrder,
  type JournalPosition,
  type JournalResponse,
  type JournalSignal,
  type JournalStrategy,
} from "../../lib/api";
import { instTypeLabel, percentValue, signedTone, signedValue } from "../../lib/display";
import { cn } from "../../lib/utils";

const MODE_LABELS = {
  manual: "人工",
  paper: "模拟盘",
  live: "实盘",
} as const;

const ENTRY_LABELS: Record<string, string> = {
  signal: "信号",
  order: "订单",
  fill: "成交",
  mode_change: "模式",
  risk_block: "风控",
  settings: "设置",
  confirmation: "确认",
};

function moment(iso: string): string {
  return `${iso.slice(0, 16).replace("T", " ")} UTC`;
}

function sourceLabel(source: string): string {
  if (source === "backtest:none") return "还没有回测";
  if (source === "execution:no_fills") return "还没有成交";
  return source;
}

function Empty({ children }: { children: string }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

function Th({ children }: { children: string }) {
  return <th className="py-2 pr-3 text-left text-xs font-medium last:pr-0">{children}</th>;
}

/**
 * Trades 页：执行模式、策略对照、持仓、订单、成交、信号与交易日志。
 *
 * 页面只展示后端返回的数值与来源，不做派生计算；回测预期与实际成交是两个独立字段，
 * 各自显示自己的来源，不互相代替。
 */
export default function TradesPage() {
  const [journal, setJournal] = useState<JournalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchJournal()
      .then((body) => {
        if (active) setJournal(body);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "交易历史加载失败");
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <>
      <PageHeading
        eyebrow="Trades"
        title="交易"
        description="持仓、订单、成交、信号与执行模式。真实交易默认关闭，未获用户授权不会下单。"
      />

      {error ? (
        <Card className="mb-6 border-rose-600/40">
          <CardContent className="pt-6 text-sm text-rose-600 dark:text-rose-400">{error}</CardContent>
        </Card>
      ) : null}

      {journal === null ? (
        <Card>
          <CardContent className="pt-6 text-sm text-muted-foreground">
            {error ? "无法读取交易历史。" : "正在读取交易历史…"}
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 xl:grid-cols-2">
          <ModeCard journal={journal} />
          <StrategyComparison strategies={journal.strategies} />
          <PositionsCard positions={journal.positions} mode={journal.mode} />
          <OrdersCard orders={journal.orders} />
          <FillsCard fills={journal.fills} />
          <SignalsCard signals={journal.signals} />
          <JournalEntriesCard entries={journal.items} total={journal.total} />
        </div>
      )}
    </>
  );
}

function ModeCard({ journal }: { journal: JournalResponse }) {
  const counts = [
    ["持仓", journal.positions.length],
    ["订单", journal.orders.length],
    ["成交", journal.fills.length],
    ["信号", journal.signals.length],
    ["日志", journal.total],
  ] as const;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-baseline justify-between gap-3">
          <CardTitle>执行模式</CardTitle>
          <span className="rounded-full border px-2.5 py-0.5 text-xs font-medium">
            {MODE_LABELS[journal.mode]}
          </span>
        </div>
        <CardDescription>
          当前模式的订单与成交才计入实际收益。实盘开关需要显式二次确认风险。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-3 gap-3 sm:grid-cols-5">
          {counts.map(([label, value]) => (
            <div key={label} className="rounded-md border px-3 py-2">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="font-mono text-lg tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

function StrategyComparison({ strategies }: { strategies: JournalStrategy[] }) {
  return (
    <Card className="xl:col-span-2">
      <CardHeader>
        <CardTitle>回测预期与实际成交</CardTitle>
        <CardDescription>
          同一策略的两个收益分开取值：预期来自某一次回测运行，实际来自该策略归属的成交。
          比率写法里 0.05 表示 5%，两个来源字段都显示在数值下方。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {strategies.length === 0 ? (
          <Empty>还没有策略实例。</Empty>
        ) : (
          strategies.map((strategy) => (
            <div
              key={strategy.instance_id}
              className="grid gap-5 border-b pb-6 last:border-b-0 last:pb-0 lg:grid-cols-[minmax(0,1fr)_360px]"
            >
              <div className="space-y-3">
                <div>
                  <p className="text-sm font-medium">{strategy.name}</p>
                  <p className="font-mono text-xs text-muted-foreground">
                    {strategy.strategy_id} · v{strategy.strategy_version} · {strategy.bar} ·{" "}
                    {MODE_LABELS[strategy.execution_mode]}
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <ValueBlock
                    label="回测预期收益"
                    value={strategy.expected_return ?? null}
                    source={strategy.expected_source}
                    empty="没有可用的回测运行"
                  />
                  <ValueBlock
                    label="实际成交收益"
                    value={strategy.actual_return}
                    source={strategy.actual_source}
                    empty="还没有平仓成交"
                  />
                </div>
                <p className="text-xs text-muted-foreground">
                  成交 {strategy.fill_count} 笔 · 资金变化 {signedValue(strategy.net_cash_flow)}
                </p>
              </div>
              <div>
                <p className="mb-1 text-xs text-muted-foreground">实际成交累计收益率（%）</p>
                <LineChart
                  points={strategy.actual_curve.map((point) => ({
                    time: point.at,
                    price: String(Number(point.value) * 100),
                  }))}
                  label="实际成交累计收益率"
                  emptyText="还没有平仓成交，无法画出实际收益曲线。"
                />
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

function ValueBlock({
  label,
  value,
  source,
  empty,
}: {
  label: string;
  value: string | null;
  source: string;
  empty: string;
}) {
  return (
    <div className="rounded-md border px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("font-mono text-lg tabular-nums", value && signedTone(value))}>
        {value === null ? "—" : percentValue(value)}
      </p>
      <p className="break-words font-mono text-[11px] text-muted-foreground">
        {value === null ? empty : sourceLabel(source)}
      </p>
    </div>
  );
}

function PositionsCard({
  positions,
  mode,
}: {
  positions: JournalPosition[];
  mode: JournalResponse["mode"];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>持仓</CardTitle>
        <CardDescription>账户实际持仓，按产品与方向归并；{MODE_LABELS[mode]}模式。</CardDescription>
      </CardHeader>
      <CardContent>
        {positions.length === 0 ? (
          <Empty>当前没有持仓。</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <Th>产品</Th>
                  <Th>类别</Th>
                  <Th>方向</Th>
                  <Th>数量</Th>
                  <Th>均价</Th>
                  <Th>杠杆</Th>
                  <Th>强平价</Th>
                </tr>
              </thead>
              <tbody>
                {positions.map((position) => (
                  <tr key={`${position.product_key}-${position.side}`} className="border-b last:border-b-0">
                    <td className="py-2 pr-3 font-mono">{position.product_key}</td>
                    <td className="py-2 pr-3">{instTypeLabel(position.inst_type)}</td>
                    <td className="py-2 pr-3">{position.side === "long" ? "多" : "空"}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{position.qty}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{position.avg_cost}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{position.leverage ?? "—"}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">
                      {position.liquidation_price ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function OrdersCard({ orders }: { orders: JournalOrder[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>订单</CardTitle>
        <CardDescription>按创建时刻排列；已拒单在契约里显示为 rejected。</CardDescription>
      </CardHeader>
      <CardContent>
        {orders.length === 0 ? (
          <Empty>还没有订单。</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <Th>时间</Th>
                  <Th>标的</Th>
                  <Th>方向</Th>
                  <Th>类型</Th>
                  <Th>数量</Th>
                  <Th>已成交</Th>
                  <Th>均价</Th>
                  <Th>状态</Th>
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <tr key={order.client_order_id} className="border-b last:border-b-0">
                    <td className="py-2 pr-3 font-mono text-xs">{moment(order.created_at)}</td>
                    <td className="py-2 pr-3 font-mono">{order.inst_id}</td>
                    <td className="py-2 pr-3">{order.side === "buy" ? "买" : "卖"}</td>
                    <td className="py-2 pr-3">{order.order_type === "market" ? "市价" : "限价"}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{order.qty}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{order.filled_qty}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">
                      {order.avg_fill_price ?? "—"}
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs">{order.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function FillsCard({ fills }: { fills: JournalFill[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>成交</CardTitle>
        <CardDescription>每笔成交的价格、数量与手续费；手续费按扣费币种记录。</CardDescription>
      </CardHeader>
      <CardContent>
        {fills.length === 0 ? (
          <Empty>还没有成交。</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <Th>时间</Th>
                  <Th>标的</Th>
                  <Th>方向</Th>
                  <Th>价格</Th>
                  <Th>数量</Th>
                  <Th>手续费</Th>
                </tr>
              </thead>
              <tbody>
                {fills.map((fill, index) => (
                  <tr key={fill.fill_id || `${fill.order_id}-${index}`} className="border-b last:border-b-0">
                    <td className="py-2 pr-3 font-mono text-xs">{moment(fill.filled_at)}</td>
                    <td className="py-2 pr-3 font-mono">{fill.inst_id}</td>
                    <td className="py-2 pr-3">{fill.side === "buy" ? "买" : "卖"}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{fill.price}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{fill.qty}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">
                      {fill.fee} {fill.fee_currency}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SignalsCard({ signals }: { signals: JournalSignal[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>策略信号</CardTitle>
        <CardDescription>信号只表达方向与强度，不直接产生订单。</CardDescription>
      </CardHeader>
      <CardContent>
        {signals.length === 0 ? (
          <Empty>还没有信号。</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <Th>时间</Th>
                  <Th>标的</Th>
                  <Th>方向</Th>
                  <Th>强度</Th>
                  <Th>价格</Th>
                  <Th>原因</Th>
                </tr>
              </thead>
              <tbody>
                {signals.map((signal) => (
                  <tr key={signal.signal_id} className="border-b last:border-b-0">
                    <td className="py-2 pr-3 font-mono text-xs">{moment(signal.generated_at)}</td>
                    <td className="py-2 pr-3 font-mono">{signal.inst_id}</td>
                    <td className="py-2 pr-3">{signal.side === "long" ? "多" : "空"}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">
                      {signal.strength.toFixed(2)}
                    </td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{signal.price ?? "—"}</td>
                    <td className="py-2 pr-3 text-xs text-muted-foreground">{signal.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function JournalEntriesCard({ entries, total }: { entries: JournalEntry[]; total: number }) {
  return (
    <Card className="xl:col-span-2">
      <CardHeader>
        <div className="flex items-baseline justify-between gap-3">
          <CardTitle>交易日志</CardTitle>
          <span className="text-xs text-muted-foreground">{total} 条</span>
        </div>
        <CardDescription>条目由已有事实派生，按时间倒序；journal 不单独保存一份。</CardDescription>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <Empty>还没有日志条目。</Empty>
        ) : (
          <ul className="space-y-2">
            {entries.map((entry) => (
              <li key={entry.entry_id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
                <span className="font-mono text-xs text-muted-foreground">
                  {moment(entry.created_at)}
                </span>
                <span className="rounded-full border px-2 py-0.5 text-xs">
                  {ENTRY_LABELS[entry.category] ?? entry.category}
                </span>
                {entry.inst_id ? <span className="font-mono text-xs">{entry.inst_id}</span> : null}
                <span className="text-muted-foreground">{entry.message}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
