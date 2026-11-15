import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  RESEARCH_NOTE_SORT_OPTIONS,
  RESEARCH_NOTE_TYPE_OPTIONS,
  researchNoteType,
  type ResearchNoteFilters,
  type ResearchNoteSort,
} from "../../lib/journal";
import { inputClassName, withCurrentOption, type SelectOption } from "./fields";
import { Field, SelectField } from "./shared";

export type JournalFiltersProps = {
  value: ResearchNoteFilters;
  instruments: ReadonlyArray<SelectOption>;
  strategies: ReadonlyArray<SelectOption>;
  backtests: ReadonlyArray<SelectOption>;
  onChange: (next: ResearchNoteFilters) => void;
  onReset: () => void;
};

/** 筛选条：所有条件原样传给 `GET /api/research-notes`，页面不再二次过滤。 */
export function JournalFilters({
  value,
  instruments,
  strategies,
  backtests,
  onChange,
  onReset,
}: JournalFiltersProps) {
  const update = (patch: Partial<ResearchNoteFilters>) => onChange({ ...value, ...patch });

  return (
    <Card>
      <CardHeader>
        <CardTitle>筛选</CardTitle>
        <CardDescription>筛选与排序由接口执行；清空条件即恢复全部记录。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <SelectField
            id="journal-filter-type"
            label="类型"
            value={value.type ?? ""}
            options={[{ value: "", label: "全部类型" }, ...RESEARCH_NOTE_TYPE_OPTIONS]}
            onChange={(next) => update({ type: researchNoteType(next) ?? undefined })}
          />
          <SelectField
            id="journal-filter-instrument"
            label="标的"
            value={value.instrumentId ?? ""}
            options={[
              { value: "", label: "全部标的" },
              ...withCurrentOption(
                instruments,
                value.instrumentId,
                `${value.instrumentId ?? ""}（不在当前列表）`,
              ),
            ]}
            onChange={(next) => update({ instrumentId: next === "" ? undefined : next })}
          />
          <SelectField
            id="journal-filter-strategy"
            label="策略"
            value={value.strategyId ?? ""}
            options={[
              { value: "", label: "全部策略" },
              ...withCurrentOption(
                strategies,
                value.strategyId,
                `${value.strategyId ?? ""}（不在当前列表）`,
              ),
            ]}
            onChange={(next) => update({ strategyId: next === "" ? undefined : next })}
          />
          <SelectField
            id="journal-filter-backtest"
            label="回测"
            value={value.backtestId ?? ""}
            options={[
              { value: "", label: "全部回测" },
              ...withCurrentOption(
                backtests,
                value.backtestId,
                `${value.backtestId ?? ""}（不在当前列表）`,
              ),
            ]}
            onChange={(next) => update({ backtestId: next === "" ? undefined : next })}
          />
          <Field label="起始日期" htmlFor="journal-filter-from" hint="北京时间，含当天。">
            <input
              id="journal-filter-from"
              type="date"
              className={inputClassName}
              value={value.from ?? ""}
              onChange={(event) => update({ from: event.target.value || undefined })}
            />
          </Field>
          <Field label="截止日期" htmlFor="journal-filter-to" hint="北京时间，含当天。">
            <input
              id="journal-filter-to"
              type="date"
              className={inputClassName}
              value={value.to ?? ""}
              onChange={(event) => update({ to: event.target.value || undefined })}
            />
          </Field>
          <SelectField
            id="journal-filter-sort"
            label="排序"
            value={value.sort ?? "created_at_desc"}
            options={RESEARCH_NOTE_SORT_OPTIONS}
            onChange={(next) => update({ sort: next as ResearchNoteSort })}
          />
        </div>
        <Button type="button" variant="outline" size="sm" onClick={onReset}>
          重置筛选
        </Button>
      </CardContent>
    </Card>
  );
}
