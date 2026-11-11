import { useState } from "react";

import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import type {
  StrategyDefinition,
  StrategyInstanceCreateRequest,
  StrategyParamSpec,
  StrategyParamValue,
} from "../../lib/api";

const INPUT_CLASS =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";
const LABEL_CLASS = "space-y-1.5 text-sm";

/** 表单里的参数值：输入框一律按文本保存，提交时按 `kind` 转成契约要求的值。 */
type RawValue = string | boolean;

function initialParams(template: StrategyDefinition): Record<string, RawValue> {
  const params: Record<string, RawValue> = {};
  for (const spec of template.params) {
    params[spec.name] = spec.kind === "bool" ? Boolean(spec.default) : String(spec.default);
  }
  return params;
}

/** 空输入回落到默认值，避免把 `NaN` 送进 JSON。 */
function toParamValue(spec: StrategyParamSpec, raw: RawValue): StrategyParamValue {
  if (spec.kind === "bool") return Boolean(raw);
  const text = String(raw).trim();
  if (text === "") return spec.default;
  if (spec.kind === "int") return Number.parseInt(text, 10);
  if (spec.kind === "float") return Number.parseFloat(text);
  return text;
}

/** 标的输入：逗号或空白分隔的交易所标识；去空白即可，合法性由后端判断。 */
function splitInstIds(text: string): string[] {
  return text
    .split(/[\s,，]+/)
    .map((item) => item.trim())
    .filter((item) => item !== "");
}

export type StrategyFormProps = {
  template: StrategyDefinition;
  busy: boolean;
  onSubmit: (payload: StrategyInstanceCreateRequest) => void;
};

/**
 * 建实例表单：字段由所选模板的声明驱动。
 *
 * 生命周期阶段与执行方式不在这里填：新建实例一律落在草稿、人工执行；阶段推进只经
 * 审批状态机（T3.6）。
 */
export function StrategyForm({ template, busy, onSubmit }: StrategyFormProps) {
  const [name, setName] = useState("");
  const [bar, setBar] = useState<string>(
    template.required_bars.includes("1d") ? "1d" : (template.required_bars[0] ?? "1d"),
  );
  const [instIds, setInstIds] = useState("");
  const [params, setParams] = useState<Record<string, RawValue>>(() => initialParams(template));

  const ready = name.trim() !== "" && splitInstIds(instIds).length > 0 && !busy;

  return (
    <Card>
      <CardHeader>
        <div className="space-y-1.5">
          <CardTitle>新建实例</CardTitle>
          <CardDescription>
            模板：{template.name}（{template.strategy_id} · v{template.version}）。参数留空时使用模板默认值。
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!ready) return;
            onSubmit({
              strategy_id: template.strategy_id,
              name: name.trim(),
              // 选项来自模板声明的周期列表，取值因此落在契约的 Bar 枚举内。
              bar: bar as StrategyInstanceCreateRequest["bar"],
              inst_ids: splitInstIds(instIds),
              params: Object.fromEntries(
                template.params.map((spec) => [spec.name, toParamValue(spec, params[spec.name])]),
              ),
            });
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <label className={LABEL_CLASS}>
              <span className="text-muted-foreground">实例名称</span>
              <input
                className={INPUT_CLASS}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="例如 BTC/ETH 配对"
                maxLength={128}
                required
              />
            </label>
            <label className={LABEL_CLASS}>
              <span className="text-muted-foreground">周期</span>
              <select
                className={INPUT_CLASS}
                value={bar}
                onChange={(event) => setBar(event.target.value)}
              >
                {template.required_bars.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className={LABEL_CLASS}>
            <span className="text-muted-foreground">标的（交易所标识，逗号分隔）</span>
            <input
              className={INPUT_CLASS}
              value={instIds}
              onChange={(event) => setInstIds(event.target.value)}
              placeholder="BTC-USDT, ETH-USDT"
              required
            />
          </label>

          <div className="grid gap-4 sm:grid-cols-3">
            {template.params.map((spec) => (
              <label key={spec.name} className={LABEL_CLASS}>
                <span className="text-muted-foreground">{spec.title}</span>
                {spec.kind === "bool" ? (
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-input"
                    checked={Boolean(params[spec.name])}
                    onChange={(event) =>
                      setParams((current) => ({ ...current, [spec.name]: event.target.checked }))
                    }
                  />
                ) : (
                  <input
                    className={INPUT_CLASS}
                    type={spec.kind === "string" ? "text" : "number"}
                    value={String(params[spec.name] ?? "")}
                    min={spec.minimum ?? undefined}
                    max={spec.maximum ?? undefined}
                    step={spec.kind === "int" ? 1 : "any"}
                    onChange={(event) =>
                      setParams((current) => ({ ...current, [spec.name]: event.target.value }))
                    }
                  />
                )}
                <span className="block text-xs text-muted-foreground">
                  {spec.minimum}–{spec.maximum}，默认 {spec.default}
                </span>
              </label>
            ))}
          </div>

          <div>
            <Button type="submit" disabled={!ready}>
              {busy ? "创建中…" : "建实例"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
