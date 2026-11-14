import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";

import { Button } from "../../components/ui/button";
import {
  createStrategy,
  createStrategyVersion,
  replaceStrategyVersionInstruments,
  updateStrategy,
  type StrategyCreatedResponse,
  type StrategyDetail,
  type StrategyVersionCreateRequest,
  type StrategyVersionDetail,
} from "../../lib/api";
import {
  joinInstrumentIds,
  parseJsonObject,
  parseOptionalJsonObject,
  prettyJson,
  splitInstrumentIds,
  STRATEGY_CATEGORY_OPTIONS,
  STRATEGY_DIRECTION_OPTIONS,
  STRATEGY_STATUS_OPTIONS,
  STRATEGY_TIMEFRAME_OPTIONS,
  type StrategyDirection,
  type StrategyStatus,
  type StrategyTimeframe,
} from "../../lib/strategies";

const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";
const TEXTAREA_CLASS =
  "min-h-24 w-full rounded-md border border-input bg-transparent p-3 font-mono text-xs leading-5 outline-none focus-visible:ring-2 focus-visible:ring-ring";
const LABEL_CLASS = "space-y-1.5 text-sm";

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
        className="relative z-10 max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-t-xl border bg-card p-5 shadow-lg sm:rounded-lg sm:p-6"
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

type CreateFields = {
  name: string;
  category: string;
  description: string;
  timeframe: StrategyTimeframe;
  direction: StrategyDirection;
  ruleJson: string;
  parameters: string;
  positionSizing: string;
  costModel: string;
  instrumentIds: string;
  changeNote: string;
};

const EMPTY_CREATE_FIELDS: CreateFields = {
  name: "",
  category: "directional",
  description: "",
  timeframe: "1d",
  direction: "long_only",
  ruleJson: "",
  parameters: "{}",
  positionSizing: "",
  costModel: "",
  instrumentIds: "",
  changeNote: "",
};

const RULE_PLACEHOLDER =
  '{"timeframe":"1d","direction":"long_only","entry":{"all":[{"left":"MA(20)","op":">","right":"MA(60)"}]},"exit":{"any":[{"left":"MA(20)","op":"<","right":"MA(60)"}]}}';

function CategorySelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const known = STRATEGY_CATEGORY_OPTIONS.some((option) => option.value === value);
  return (
    <select
      className={INPUT_CLASS}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {known ? null : <option value={value}>{value}</option>}
      {STRATEGY_CATEGORY_OPTIONS.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function TimeframeSelect({
  value,
  onChange,
}: {
  value: StrategyTimeframe;
  onChange: (value: StrategyTimeframe) => void;
}) {
  return (
    <select
      className={INPUT_CLASS}
      value={value}
      onChange={(event) => onChange(event.target.value as StrategyTimeframe)}
    >
      {STRATEGY_TIMEFRAME_OPTIONS.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function DirectionSelect({
  value,
  onChange,
}: {
  value: StrategyDirection;
  onChange: (value: StrategyDirection) => void;
}) {
  return (
    <select
      className={INPUT_CLASS}
      value={value}
      onChange={(event) => onChange(event.target.value as StrategyDirection)}
    >
      {STRATEGY_DIRECTION_OPTIONS.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export function CreateStrategyDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (created: StrategyCreatedResponse) => void;
}) {
  const [fields, setFields] = useState<CreateFields>(EMPTY_CREATE_FIELDS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (patch: Partial<CreateFields>) =>
    setFields((current) => ({ ...current, ...patch }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createStrategy({
        name: fields.name.trim(),
        category: fields.category,
        description: fields.description.trim() || null,
        timeframe: fields.timeframe,
        direction: fields.direction,
        rule_json: parseJsonObject(fields.ruleJson, "规则 JSON"),
        parameters: parseJsonObject(fields.parameters, "参数"),
        instrument_ids: splitInstrumentIds(fields.instrumentIds),
        position_sizing: parseOptionalJsonObject(fields.positionSizing, "仓位规则"),
        cost_model: parseOptionalJsonObject(fields.costModel, "成本模型"),
        change_note: fields.changeNote.trim() || null,
      });
      onCreated(created);
    } catch (reason: unknown) {
      setError(messageOf(reason, "创建策略失败"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title="新建策略"
      description="创建策略与第一个草稿版本。规则 JSON 由后端校验；标的标识按行或逗号分隔。"
      onClose={onClose}
    >
      <form className="grid gap-4" onSubmit={(event) => void submit(event)}>
        {error ? <ErrorNotice message={error} /> : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">策略名称</span>
            <input
              className={INPUT_CLASS}
              value={fields.name}
              onChange={(event) => update({ name: event.target.value })}
              required
            />
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">类别（同时决定回测模板）</span>
            <CategorySelect value={fields.category} onChange={(value) => update({ category: value })} />
          </label>
        </div>

        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">描述</span>
          <input
            className={INPUT_CLASS}
            value={fields.description}
            onChange={(event) => update({ description: event.target.value })}
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">周期</span>
            <TimeframeSelect
              value={fields.timeframe}
              onChange={(value) => update({ timeframe: value })}
            />
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">方向</span>
            <DirectionSelect
              value={fields.direction}
              onChange={(value) => update({ direction: value })}
            />
          </label>
        </div>

        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">规则 JSON</span>
          <textarea
            className={TEXTAREA_CLASS}
            value={fields.ruleJson}
            onChange={(event) => update({ ruleJson: event.target.value })}
            placeholder={RULE_PLACEHOLDER}
            required
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">参数 JSON</span>
            <textarea
              className={TEXTAREA_CLASS}
              value={fields.parameters}
              onChange={(event) => update({ parameters: event.target.value })}
              required
            />
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">仓位规则 JSON（可选）</span>
            <textarea
              className={TEXTAREA_CLASS}
              value={fields.positionSizing}
              onChange={(event) => update({ positionSizing: event.target.value })}
            />
          </label>
        </div>

        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">成本模型 JSON（可选）</span>
          <textarea
            className={TEXTAREA_CLASS}
            value={fields.costModel}
            onChange={(event) => update({ costModel: event.target.value })}
          />
        </label>

        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">标的集合（每行一个，或用逗号分隔）</span>
          <textarea
            className={TEXTAREA_CLASS}
            value={fields.instrumentIds}
            onChange={(event) => update({ instrumentIds: event.target.value })}
            placeholder="AAPL-USDT-SWAP"
          />
        </label>

        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">变更说明（可选）</span>
          <input
            className={INPUT_CLASS}
            value={fields.changeNote}
            onChange={(event) => update({ changeNote: event.target.value })}
          />
        </label>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "创建中…" : "创建策略"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

type VersionFields = {
  timeframe: StrategyTimeframe;
  direction: StrategyDirection;
  ruleJson: string;
  parameters: string;
  positionSizing: string;
  costModel: string;
  instrumentIds: string;
  changeNote: string;
};

function versionFieldsFrom(current: StrategyVersionDetail): VersionFields {
  return {
    timeframe: current.timeframe,
    direction: current.direction,
    ruleJson: prettyJson(current.rule_json),
    parameters: prettyJson(current.parameters),
    positionSizing: prettyJson(current.position_sizing),
    costModel: prettyJson(current.cost_model),
    instrumentIds: joinInstrumentIds(current.instrument_ids),
    changeNote: "",
  };
}

export function NewVersionDialog({
  detail,
  current,
  onClose,
  onCreated,
}: {
  detail: StrategyDetail;
  current: StrategyVersionDetail;
  onClose: () => void;
  onCreated: (version: StrategyVersionDetail) => void;
}) {
  const [fields, setFields] = useState<VersionFields>(() => versionFieldsFrom(current));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (patch: Partial<VersionFields>) =>
    setFields((value) => ({ ...value, ...patch }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const body: StrategyVersionCreateRequest = {
        timeframe: fields.timeframe,
        direction: fields.direction,
        rule_json: parseJsonObject(fields.ruleJson, "规则 JSON"),
        parameters: parseJsonObject(fields.parameters, "参数"),
        position_sizing: parseOptionalJsonObject(fields.positionSizing, "仓位规则"),
        cost_model: parseOptionalJsonObject(fields.costModel, "成本模型"),
        instrument_ids: splitInstrumentIds(fields.instrumentIds),
        change_note: fields.changeNote.trim() || null,
      };
      onCreated(await createStrategyVersion(detail.id, body));
    } catch (reason: unknown) {
      setError(messageOf(reason, "创建新版本失败"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title={`基于 ${detail.name} 创建新版本`}
      description="提交后生成下一个版本；当前版本与它引用的回测保持不变。"
      onClose={onClose}
    >
      <form className="grid gap-4" onSubmit={(event) => void submit(event)}>
        {error ? <ErrorNotice message={error} /> : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">周期</span>
            <TimeframeSelect
              value={fields.timeframe}
              onChange={(value) => update({ timeframe: value })}
            />
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">方向</span>
            <DirectionSelect
              value={fields.direction}
              onChange={(value) => update({ direction: value })}
            />
          </label>
        </div>

        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">规则 JSON</span>
          <textarea
            className={TEXTAREA_CLASS}
            value={fields.ruleJson}
            onChange={(event) => update({ ruleJson: event.target.value })}
            required
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">参数 JSON</span>
            <textarea
              className={TEXTAREA_CLASS}
              value={fields.parameters}
              onChange={(event) => update({ parameters: event.target.value })}
              required
            />
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">仓位规则 JSON</span>
            <textarea
              className={TEXTAREA_CLASS}
              value={fields.positionSizing}
              onChange={(event) => update({ positionSizing: event.target.value })}
            />
          </label>
        </div>

        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">成本模型 JSON</span>
          <textarea
            className={TEXTAREA_CLASS}
            value={fields.costModel}
            onChange={(event) => update({ costModel: event.target.value })}
          />
        </label>

        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">标的集合（每行一个，或用逗号分隔）</span>
          <textarea
            className={TEXTAREA_CLASS}
            value={fields.instrumentIds}
            onChange={(event) => update({ instrumentIds: event.target.value })}
          />
        </label>

        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">变更说明</span>
          <input
            className={INPUT_CLASS}
            value={fields.changeNote}
            onChange={(event) => update({ changeNote: event.target.value })}
          />
        </label>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "创建中…" : "创建新版本"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function MetadataDialog({
  detail,
  onClose,
  onUpdated,
}: {
  detail: StrategyDetail;
  onClose: () => void;
  onUpdated: () => void;
}) {
  const [name, setName] = useState(detail.name);
  const [category, setCategory] = useState(detail.category);
  const [description, setDescription] = useState(detail.description ?? "");
  const [status, setStatus] = useState<StrategyStatus>(detail.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await updateStrategy(detail.id, {
        name: name.trim(),
        category,
        description: description.trim() || null,
        status,
      });
      onUpdated();
    } catch (reason: unknown) {
      setError(messageOf(reason, "更新策略失败"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title="编辑策略元数据"
      description="名称、类别、描述与状态不属于版本输入；只改这些字段不会生成新版本。"
      onClose={onClose}
    >
      <form className="grid gap-4" onSubmit={(event) => void submit(event)}>
        {error ? <ErrorNotice message={error} /> : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">策略名称</span>
            <input
              className={INPUT_CLASS}
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </label>
          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">类别（同时决定回测模板）</span>
            <CategorySelect value={category} onChange={setCategory} />
          </label>
        </div>
        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">描述</span>
          <input
            className={INPUT_CLASS}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">状态</span>
          <select
            className={INPUT_CLASS}
            value={status}
            onChange={(event) => setStatus(event.target.value as StrategyStatus)}
          >
            {STRATEGY_STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "保存中…" : "保存"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function InstrumentsDialog({
  detail,
  current,
  onClose,
  onUpdated,
}: {
  detail: StrategyDetail;
  current: StrategyVersionDetail;
  onClose: () => void;
  onUpdated: (version: StrategyVersionDetail) => void;
}) {
  const [text, setText] = useState(() => joinInstrumentIds(current.instrument_ids));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      onUpdated(
        await replaceStrategyVersionInstruments(detail.id, current.version, {
          instrument_ids: splitInstrumentIds(text),
        }),
      );
    } catch (reason: unknown) {
      setError(messageOf(reason, "调整标的失败"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title={`调整 ${detail.name} 当前版本的标的`}
      description="整批替换当前版本的标的集合；旧版本不提供修改入口。标的必须已经在标的表里。"
      onClose={onClose}
    >
      <form className="grid gap-4" onSubmit={(event) => void submit(event)}>
        {error ? <ErrorNotice message={error} /> : null}
        <label className={LABEL_CLASS}>
          <span className="text-muted-foreground">标的集合（每行一个，或用逗号分隔）</span>
          <textarea
            className={TEXTAREA_CLASS}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </label>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "保存中…" : "保存标的"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
