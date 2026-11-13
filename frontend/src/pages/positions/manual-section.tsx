import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { ApiError } from "../../lib/api";
import { formatBeijingTime } from "../../lib/display";
import {
  actionLabel,
  addManualTrade,
  buildCreatePayload,
  buildTradePayload,
  buildUpdatePayload,
  createManualPosition,
  deleteManualPosition,
  fetchManualPositions,
  fetchManualTrades,
  localDateTimeValue,
  newIdempotencyKey,
  positionStatusLabel,
  quotePnlText,
  quoteSourceText,
  quoteText,
  sideLabel,
  tradePnlText,
  updateManualPosition,
  type CreatePositionFields,
  type ManualPosition,
  type ManualTrade,
  type ManualTradeAction,
  type TradeFields,
  type UpdatePositionFields,
} from "../../lib/manual-positions";
import { valueOrMissing } from "../../lib/positions";
import { cn } from "../../lib/utils";

const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";
const LABEL_CLASS = "space-y-1.5 text-sm";

type StatusFilter = "open" | "closed";

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

function Dialog({
  title,
  description,
  onClose,
  children,
}: {
  title: string;
  description: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const titleId = useId();

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      <button
        type="button"
        aria-label="关闭对话框"
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative z-10 max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-t-xl border bg-card p-5 shadow-lg sm:rounded-lg sm:p-6"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h2 id={titleId} className="text-base font-semibold tracking-tight">
              {title}
            </h2>
            <p className="text-sm leading-5 text-muted-foreground">{description}</p>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            关闭
          </Button>
        </div>
        {children}
      </div>
    </div>
  );
}

const EMPTY_CREATE_FIELDS: CreatePositionFields = {
  instId: "",
  side: "long",
  quantity: "",
  avgCost: "",
  stopPx: "",
  leverage: "",
  note: "",
};

function CreatePositionDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (position: ManualPosition) => void;
}) {
  const [fields, setFields] = useState<CreatePositionFields>(EMPTY_CREATE_FIELDS);
  const [idempotencyKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (patch: Partial<CreatePositionFields>) =>
    setFields((current) => ({ ...current, ...patch }));

  const ready =
    fields.instId.trim() !== "" &&
    fields.quantity.trim() !== "" &&
    fields.avgCost.trim() !== "" &&
    !busy;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createManualPosition(
        buildCreatePayload(fields, idempotencyKey),
      );
      onCreated(created);
    } catch (reason: unknown) {
      setError(messageOf(reason, "创建手动持仓失败"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title="新建手动持仓"
      description="只记录本地账本，不向交易所发送订单。数量、平均成本与可选字段都由后端校验。"
      onClose={onClose}
    >
      <form className="grid gap-4" onSubmit={(event) => void submit(event)}>
        {error ? <ErrorNotice message={error} /> : null}

        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">标的标识</span>
          <input
            className={INPUT_CLASS}
            value={fields.instId}
            onChange={(event) => update({ instId: event.target.value })}
            placeholder="例如 AAPL-USDT-SWAP"
            required
            autoFocus
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">方向</span>
            <select
              className={INPUT_CLASS}
              value={fields.side}
              onChange={(event) =>
                update({ side: event.target.value as CreatePositionFields["side"] })
              }
            >
              <option value="long">多</option>
              <option value="short">空</option>
            </select>
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">数量</span>
            <input
              className={INPUT_CLASS}
              inputMode="decimal"
              value={fields.quantity}
              onChange={(event) => update({ quantity: event.target.value })}
              placeholder="例如 8"
              required
            />
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">平均成本</span>
            <input
              className={INPUT_CLASS}
              inputMode="decimal"
              value={fields.avgCost}
              onChange={(event) => update({ avgCost: event.target.value })}
              placeholder="例如 226.80"
              required
            />
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">止损价（可选）</span>
            <input
              className={INPUT_CLASS}
              inputMode="decimal"
              value={fields.stopPx}
              onChange={(event) => update({ stopPx: event.target.value })}
              placeholder="留空表示未设置"
            />
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">杠杆（可选）</span>
            <input
              className={INPUT_CLASS}
              inputMode="decimal"
              value={fields.leverage}
              onChange={(event) => update({ leverage: event.target.value })}
              placeholder="例如 3"
            />
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">备注（可选）</span>
            <input
              className={INPUT_CLASS}
              value={fields.note}
              onChange={(event) => update({ note: event.target.value })}
              maxLength={512}
            />
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={!ready}>
            {busy ? "创建中…" : "创建持仓"}
          </Button>
          <span className="text-xs text-muted-foreground">
            每次提交都带幂等键，重复提交不会重复入账。
          </span>
        </div>
      </form>
    </Dialog>
  );
}

const TRADE_ACTION_OPTIONS: { value: ManualTradeAction; label: string }[] = [
  { value: "add", label: "买入 / 加仓" },
  { value: "reduce", label: "卖出 / 减仓" },
  { value: "close", label: "清仓" },
  { value: "correct", label: "更正" },
];

function initialTradeFields(): TradeFields {
  return {
    action: "add",
    quantity: "",
    price: "",
    fee: "0",
    occurredAt: localDateTimeValue(new Date()),
    note: "",
  };
}

function TradeDialog({
  position,
  onClose,
  onDone,
}: {
  position: ManualPosition;
  onClose: () => void;
  onDone: (trade: ManualTrade) => void;
}) {
  const [fields, setFields] = useState<TradeFields>(() => initialTradeFields());
  const [idempotencyKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (patch: Partial<TradeFields>) =>
    setFields((current) => ({ ...current, ...patch }));

  const changeAction = (action: ManualTradeAction) =>
    setFields((current) => ({
      ...current,
      action,
      quantity: action === "close" ? position.quantity : current.quantity,
      fee: action === "correct" ? "0" : current.fee,
    }));

  const ready =
    fields.price.trim() !== "" &&
    fields.quantity.trim() !== "" &&
    fields.occurredAt.trim() !== "" &&
    !busy;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    const effective =
      fields.action === "close" ? { ...fields, quantity: position.quantity } : fields;
    try {
      const trade = await addManualTrade(
        position.id,
        buildTradePayload(effective, idempotencyKey),
      );
      onDone(trade);
    } catch (reason: unknown) {
      setError(messageOf(reason, "写入手动流水失败"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title={`买卖流水 · ${position.display_symbol}`}
      description="每次操作只追加一条流水，数量与平均成本由后端重算；页面不自行计算已实现盈亏。"
      onClose={onClose}
    >
      <form className="grid gap-4" onSubmit={(event) => void submit(event)}>
        {error ? <ErrorNotice message={error} /> : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">动作</span>
            <select
              className={INPUT_CLASS}
              value={fields.action}
              onChange={(event) =>
                changeAction(event.target.value as ManualTradeAction)
              }
            >
              {TRADE_ACTION_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">
              数量{fields.action === "close" ? "（清仓必须等于当前数量）" : ""}
            </span>
            <input
              className={INPUT_CLASS}
              inputMode="decimal"
              value={fields.quantity}
              onChange={(event) => update({ quantity: event.target.value })}
              readOnly={fields.action === "close"}
              required
            />
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">
              {fields.action === "correct" ? "更正后的平均成本" : "成交价"}
            </span>
            <input
              className={INPUT_CLASS}
              inputMode="decimal"
              value={fields.price}
              onChange={(event) => update({ price: event.target.value })}
              required
            />
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">发生时间</span>
            <input
              className={INPUT_CLASS}
              type="datetime-local"
              value={fields.occurredAt}
              onChange={(event) => update({ occurredAt: event.target.value })}
              required
            />
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">手续费（可选）</span>
            <input
              className={INPUT_CLASS}
              inputMode="decimal"
              value={fields.fee}
              onChange={(event) => update({ fee: event.target.value })}
              disabled={fields.action === "correct"}
            />
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">备注（可选）</span>
            <input
              className={INPUT_CLASS}
              value={fields.note}
              onChange={(event) => update({ note: event.target.value })}
              maxLength={512}
            />
          </label>
        </div>

        <p className="text-xs leading-5 text-muted-foreground">
          {fields.action === "correct"
            ? "更正会直接把数量和平均成本改成填写的值，不产生已实现盈亏，也不接受手续费。"
            : fields.action === "close"
              ? "清仓数量固定为当前数量；数量不一致时后端返回 422，页面显示错误并保留输入。"
              : "已实现盈亏、操作后数量与操作后成本都由后端返回到流水里。"}
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={!ready}>
            {busy ? "提交中…" : "提交流水"}
          </Button>
          <span className="text-xs text-muted-foreground">
            本次提交的幂等键会保留到成功为止。
          </span>
        </div>
      </form>
    </Dialog>
  );
}

function EditPositionDialog({
  position,
  onClose,
  onSaved,
}: {
  position: ManualPosition;
  onClose: () => void;
  onSaved: (position: ManualPosition) => void;
}) {
  const [fields, setFields] = useState<UpdatePositionFields>({
    stopPx: position.stop_px ?? "",
    leverage: position.leverage ?? "",
    note: position.note ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (patch: Partial<UpdatePositionFields>) =>
    setFields((current) => ({ ...current, ...patch }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const updated = await updateManualPosition(
        position.id,
        buildUpdatePayload(fields),
      );
      onSaved(updated);
    } catch (reason: unknown) {
      setError(messageOf(reason, "修改手动持仓失败"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title={`编辑手动持仓 · ${position.display_symbol}`}
      description="只能修改止损价、杠杆与备注；数量和平均成本只能通过流水改变。留空表示清除该字段。"
      onClose={onClose}
    >
      <form className="grid gap-4" onSubmit={(event) => void submit(event)}>
        {error ? <ErrorNotice message={error} /> : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">止损价</span>
            <input
              className={INPUT_CLASS}
              inputMode="decimal"
              value={fields.stopPx}
              onChange={(event) => update({ stopPx: event.target.value })}
            />
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">杠杆</span>
            <input
              className={INPUT_CLASS}
              inputMode="decimal"
              value={fields.leverage}
              onChange={(event) => update({ leverage: event.target.value })}
            />
          </label>
        </div>

        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">备注</span>
          <input
            className={INPUT_CLASS}
            value={fields.note}
            onChange={(event) => update({ note: event.target.value })}
            maxLength={512}
          />
        </label>

        <Button type="submit" disabled={busy} className="justify-self-start">
          {busy ? "保存中…" : "保存修改"}
        </Button>
      </form>
    </Dialog>
  );
}

function TradeResultNotice({
  trade,
  duplicate,
  onDismiss,
}: {
  trade: ManualTrade;
  duplicate: boolean;
  onDismiss: () => void;
}) {
  return (
    <div
      role="status"
      className="rounded-md border border-emerald-600/40 bg-emerald-500/5 px-3 py-2 text-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span>
          最近一次流水：{actionLabel(trade.action)} {trade.quantity} @ {trade.price}
          {duplicate ? "。该幂等键已有记录，没有重复入账。" : "。"}
        </span>
        <Button type="button" variant="ghost" size="sm" onClick={onDismiss}>
          关闭
        </Button>
      </div>
      <dl className="mt-2 grid gap-2 sm:grid-cols-3">
        {[
          ["已实现盈亏", tradePnlText(trade.realized_pnl)],
          ["操作后数量", trade.position_quantity_after],
          ["操作后成本", trade.position_avg_cost_after],
        ].map(([label, value]) => (
          <div key={label} className="rounded-md border px-3 py-2">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="mt-1 truncate font-mono text-sm tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function PositionsTable({
  positions,
  onTrade,
  onEdit,
  onDelete,
  onSelectTrades,
  selectedPositionId,
}: {
  positions: ManualPosition[];
  onTrade: (position: ManualPosition) => void;
  onEdit: (position: ManualPosition) => void;
  onDelete: (position: ManualPosition) => void;
  onSelectTrades: (position: ManualPosition) => void;
  selectedPositionId: string | null;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[980px] text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            {[
              "标的",
              "方向",
              "数量",
              "平均成本",
              "止损 / 杠杆",
              "状态",
              "最新价",
              "市值 / 未实现盈亏",
              "价格来源",
              "更新时间",
              "操作",
            ].map((label) => (
              <th
                key={label}
                scope="col"
                className={cn(
                  "whitespace-nowrap py-2 pr-3 font-medium",
                  label === "标的" ? "text-left" : "text-right",
                  label === "操作" && "pr-0",
                )}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => (
            <tr
              key={position.id}
              className={cn(
                "border-b last:border-0",
                position.id === selectedPositionId && "bg-muted/40",
              )}
            >
              <td className="py-3 pr-3">
                <div className="font-medium">{position.display_symbol}</div>
                <div className="text-xs text-muted-foreground">
                  {position.name} · {position.inst_id}
                </div>
              </td>
              <td className="whitespace-nowrap px-2 py-3 text-right">
                {sideLabel(position.side)}
              </td>
              <td className="whitespace-nowrap px-2 py-3 text-right font-mono tabular-nums">
                {position.quantity}
              </td>
              <td className="whitespace-nowrap px-2 py-3 text-right font-mono tabular-nums">
                {position.avg_cost}
              </td>
              <td className="whitespace-nowrap px-2 py-3 text-right font-mono tabular-nums">
                <div>{valueOrMissing(position.stop_px)}</div>
                <div className="text-xs text-muted-foreground">
                  杠杆 {valueOrMissing(position.leverage)}
                </div>
              </td>
              <td className="whitespace-nowrap px-2 py-3 text-right">
                <span
                  className={cn(
                    "whitespace-nowrap rounded-full border px-2 py-0.5 text-xs",
                    position.status === "open"
                      ? "border-emerald-600/40 text-emerald-700 dark:text-emerald-400"
                      : "text-muted-foreground",
                  )}
                >
                  {positionStatusLabel(position.status)}
                </span>
              </td>
              <td className="whitespace-nowrap px-2 py-3 text-right font-mono tabular-nums">
                {quoteText(position, position.price)}
              </td>
              <td className="whitespace-nowrap px-2 py-3 text-right font-mono tabular-nums">
                <div>{quoteText(position, position.market_value)}</div>
                <div className="text-xs">{quotePnlText(position, position.unrealized_pnl)}</div>
              </td>
              <td className="whitespace-nowrap px-2 py-3 text-right">
                {quoteSourceText(position)}
              </td>
              <td className="px-2 py-3 text-right text-xs text-muted-foreground">
                {formatBeijingTime(position.updated_at)}
              </td>
              <td className="py-3 pl-2 text-right">
                <div className="flex flex-nowrap justify-end gap-1">
                  <Button
                    type="button"
                    size="sm"
                    variant="link"
                    className="h-7 px-1"
                    onClick={() => onTrade(position)}
                    disabled={position.status === "closed"}
                  >
                    买卖
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="link"
                    className="h-7 px-1"
                    onClick={() => onSelectTrades(position)}
                  >
                    流水
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="link"
                    className="h-7 px-1"
                    onClick={() => onEdit(position)}
                  >
                    编辑
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="link"
                    className="h-7 px-1 text-destructive"
                    onClick={() => onDelete(position)}
                  >
                    删除
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradesPanel({
  position,
  trades,
  loading,
  error,
  onClose,
}: {
  position: ManualPosition;
  trades: ManualTrade[] | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1.5">
            <CardTitle>流水 · {position.display_symbol}</CardTitle>
            <CardDescription>
              按发生时间倒序；操作后数量、成本和已实现盈亏都是后端返回值。
            </CardDescription>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            收起
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {error ? <ErrorNotice message={error} /> : null}
        {loading && trades === null ? (
          <p className="text-sm text-muted-foreground">正在读取流水…</p>
        ) : trades === null || trades.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">暂无流水</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-sm">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    {[
                      "时间",
                      "动作",
                      "数量",
                      "价格",
                      "手续费",
                      "已实现盈亏",
                      "操作后数量",
                      "操作后成本",
                      "操作后状态",
                      "备注",
                    ].map((label) => (
                      <th
                        key={label}
                        scope="col"
                        className={cn(
                          "py-2 pr-3 font-medium",
                          label === "时间" || label === "备注" ? "text-left" : "text-right",
                          label === "备注" && "pr-0",
                        )}
                      >
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {trades.map((trade) => (
                    <tr key={trade.id} className="border-b last:border-0">
                      <td className="py-2 pr-3 text-xs text-muted-foreground">
                        {formatBeijingTime(trade.occurred_at)}
                      </td>
                      <td className="px-2 py-2 text-right">{actionLabel(trade.action)}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">
                        {trade.quantity}
                      </td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">
                        {trade.price}
                      </td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">
                        {trade.fee}
                      </td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">
                        {tradePnlText(trade.realized_pnl)}
                      </td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">
                        {trade.position_quantity_after}
                      </td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">
                        {trade.position_avg_cost_after}
                      </td>
                      <td className="px-2 py-2 text-right">
                        {positionStatusLabel(trade.position_status_after)}
                      </td>
                      <td className="py-2 pl-2 text-left text-xs text-muted-foreground">
                        {valueOrMissing(trade.note)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              更正流水的“价格”列是更正后的平均成本，不是成交价。
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export type ManualSectionViewProps = {
  positions: ManualPosition[] | null;
  loading: boolean;
  error: string | null;
  notice: string | null;
  filter: StatusFilter;
  onFilterChange: (filter: StatusFilter) => void;
  onRetry: () => void;
  onCreate: () => void;
  onTrade: (position: ManualPosition) => void;
  onEdit: (position: ManualPosition) => void;
  onDelete: (position: ManualPosition) => void;
  onSelectTrades: (position: ManualPosition) => void;
  selectedPosition: ManualPosition | null;
  trades: ManualTrade[] | null;
  tradesLoading: boolean;
  tradesError: string | null;
  onCloseTrades: () => void;
  lastTrade: ManualTrade | null;
  lastTradeDuplicate: boolean;
  onDismissTrade: () => void;
};

/** 纯展示组件：测试直接渲染它，不依赖网络与浏览器。 */
export function ManualSectionView({
  positions,
  loading,
  error,
  notice,
  filter,
  onFilterChange,
  onRetry,
  onCreate,
  onTrade,
  onEdit,
  onDelete,
  onSelectTrades,
  selectedPosition,
  trades,
  tradesLoading,
  tradesError,
  onCloseTrades,
  lastTrade,
  lastTradeDuplicate,
  onDismissTrade,
}: ManualSectionViewProps) {
  const openCount = positions?.filter((item) => item.status === "open").length ?? 0;
  const closedCount = positions?.filter((item) => item.status === "closed").length ?? 0;
  const visible = positions?.filter((item) => item.status === filter) ?? null;
  // 流水必须与当前选中的持仓属于同一本账本；切换持仓后旧请求的结果不得显示。
  const visibleTrades =
    selectedPosition !== null &&
    trades !== null &&
    trades.every((trade) => trade.position_id === selectedPosition.id)
      ? trades
      : null;

  return (
    <section className="grid min-w-0 gap-4" aria-label="手动持仓">
      <Card className="min-w-0">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 space-y-1.5">
              <CardTitle>手动持仓</CardTitle>
              <CardDescription>
                本地账本记录；数量、成本、市值与盈亏全部来自后端，页面不计算。
                没有行情时显示“无行情源”，不用相似标的价格替代。
              </CardDescription>
            </div>
            <Button type="button" className="shrink-0" onClick={onCreate}>
              新建持仓
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {error ? <ErrorNotice message={error} /> : null}
          {notice ? (
            <p
              role="status"
              className="rounded-md border px-3 py-2 text-sm text-muted-foreground"
            >
              {notice}
            </p>
          ) : null}
          {lastTrade ? (
            <TradeResultNotice
              trade={lastTrade}
              duplicate={lastTradeDuplicate}
              onDismiss={onDismissTrade}
            />
          ) : null}

          {positions === null ? (
            loading ? (
              <p className="text-sm text-muted-foreground">正在读取手动持仓…</p>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">手动持仓数据未返回。</p>
                <Button type="button" variant="outline" onClick={onRetry}>
                  重试
                </Button>
              </div>
            )
          ) : positions.length === 0 ? (
            <div className="space-y-3 py-6 text-center">
              <p className="text-sm text-muted-foreground">还没有手动持仓</p>
              <Button type="button" onClick={onCreate}>
                创建手动持仓
              </Button>
            </div>
          ) : (
            <>
              <div
                role="group"
                aria-label="持仓状态筛选"
                className="flex flex-wrap items-center gap-1 rounded-md border p-1"
              >
                <Button
                  type="button"
                  size="sm"
                  variant={filter === "open" ? "default" : "ghost"}
                  aria-pressed={filter === "open"}
                  onClick={() => onFilterChange("open")}
                >
                  持仓中 {openCount}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={filter === "closed" ? "default" : "ghost"}
                  aria-pressed={filter === "closed"}
                  onClick={() => onFilterChange("closed")}
                >
                  已平仓 {closedCount}
                </Button>
              </div>

              {visible === null || visible.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  暂无{filter === "open" ? "持仓中" : "已平仓"}的手动持仓。
                </p>
              ) : (
                <PositionsTable
                  positions={visible}
                  onTrade={onTrade}
                  onEdit={onEdit}
                  onDelete={onDelete}
                  onSelectTrades={onSelectTrades}
                  selectedPositionId={selectedPosition?.id ?? null}
                />
              )}
            </>
          )}
        </CardContent>
      </Card>

      {selectedPosition ? (
        <TradesPanel
          position={selectedPosition}
          trades={visibleTrades}
          loading={tradesLoading}
          error={tradesError}
          onClose={onCloseTrades}
        />
      ) : null}
    </section>
  );
}

export default function ManualSection() {
  const [positions, setPositions] = useState<ManualPosition[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [filter, setFilter] = useState<StatusFilter>("open");

  const [createOpen, setCreateOpen] = useState(false);
  const [tradeTarget, setTradeTarget] = useState<ManualPosition | null>(null);
  const [editTarget, setEditTarget] = useState<ManualPosition | null>(null);
  const [lastTrade, setLastTrade] = useState<ManualTrade | null>(null);
  const [lastTradeDuplicate, setLastTradeDuplicate] = useState(false);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [trades, setTrades] = useState<ManualTrade[] | null>(null);
  const [tradesLoading, setTradesLoading] = useState(false);
  const [tradesError, setTradesError] = useState<string | null>(null);
  const [tradesToken, setTradesToken] = useState(0);
  const knownTradeIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    fetchManualPositions()
      .then((listing) => {
        if (!active) return;
        setPositions(listing.items);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(messageOf(reason, "手动持仓加载失败"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [reloadToken]);

  useEffect(() => {
    if (selectedId === null) {
      setTrades(null);
      setTradesError(null);
      return;
    }
    let active = true;
    // 先清空上一份流水，避免新持仓标题下短暂显示旧持仓的数据。
    setTrades(null);
    setTradesLoading(true);
    setTradesError(null);

    fetchManualTrades(selectedId)
      .then((listing) => {
        if (!active) return;
        setTrades(listing.items);
        for (const trade of listing.items) knownTradeIds.current.add(trade.id);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setTradesError(messageOf(reason, "流水加载失败"));
      })
      .finally(() => {
        if (active) setTradesLoading(false);
      });

    return () => {
      active = false;
    };
  }, [selectedId, tradesToken]);

  const selectedPosition =
    positions?.find((item) => item.id === selectedId) ?? null;

  const handleCreated = (position: ManualPosition) => {
    const duplicate = positions?.some((item) => item.id === position.id) ?? false;
    setCreateOpen(false);
    setNotice(
      duplicate
        ? "该幂等键已存在，返回原持仓，没有重复入账。"
        : "已创建手动持仓。",
    );
    setReloadToken((token) => token + 1);
    setSelectedId(position.id);
  };

  const handleTradeDone = (trade: ManualTrade) => {
    const duplicate = knownTradeIds.current.has(trade.id);
    knownTradeIds.current.add(trade.id);
    setTradeTarget(null);
    setLastTrade(trade);
    setLastTradeDuplicate(duplicate);
    setNotice(null);
    setReloadToken((token) => token + 1);
    setTradesToken((token) => token + 1);
  };

  const handleDelete = (position: ManualPosition) => {
    if (!window.confirm(`删除手动持仓「${position.display_symbol}」？`)) return;
    setError(null);
    setNotice(null);
    deleteManualPosition(position.id)
      .then(() => {
        if (selectedId === position.id) setSelectedId(null);
        setNotice("已删除手动持仓。");
        setReloadToken((token) => token + 1);
      })
      .catch((reason: unknown) => {
        if (reason instanceof ApiError && reason.status === 409) {
          setError("已有流水，不能删除。");
          return;
        }
        setError(messageOf(reason, "删除手动持仓失败"));
      });
  };

  return (
    <>
      <ManualSectionView
        positions={positions}
        loading={loading}
        error={error}
        notice={notice}
        filter={filter}
        onFilterChange={setFilter}
        onRetry={() => setReloadToken((token) => token + 1)}
        onCreate={() => setCreateOpen(true)}
        onTrade={(position) => {
          setTradeTarget(position);
          setSelectedId(position.id);
        }}
        onEdit={(position) => setEditTarget(position)}
        onDelete={handleDelete}
        onSelectTrades={(position) => setSelectedId(position.id)}
        selectedPosition={selectedPosition}
        trades={trades}
        tradesLoading={tradesLoading}
        tradesError={tradesError}
        onCloseTrades={() => setSelectedId(null)}
        lastTrade={lastTrade}
        lastTradeDuplicate={lastTradeDuplicate}
        onDismissTrade={() => setLastTrade(null)}
      />

      {createOpen ? (
        <CreatePositionDialog
          onClose={() => setCreateOpen(false)}
          onCreated={handleCreated}
        />
      ) : null}

      {tradeTarget ? (
        <TradeDialog
          key={tradeTarget.id}
          position={tradeTarget}
          onClose={() => setTradeTarget(null)}
          onDone={handleTradeDone}
        />
      ) : null}

      {editTarget ? (
        <EditPositionDialog
          key={editTarget.id}
          position={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={(updated) => {
            setEditTarget(null);
            setNotice("已保存修改。");
            setReloadToken((token) => token + 1);
            if (updated.id === selectedId) setTradesToken((token) => token + 1);
          }}
        />
      ) : null}
    </>
  );
}
