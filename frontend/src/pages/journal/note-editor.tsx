import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  createResearchNote,
  updateResearchNote,
  type ResearchNoteCreateRequest,
} from "../../lib/api";
import {
  RESEARCH_NOTE_TYPE_OPTIONS,
  parseResearchNoteTags,
  type ResearchNoteType,
} from "../../lib/journal";
import { inputClassName, type JournalDraft, withCurrentOption, type SelectOption } from "./fields";
import { Field, SelectField } from "./shared";

export type JournalEditorProps = {
  noteId?: string;
  initial: JournalDraft;
  instruments: ReadonlyArray<SelectOption>;
  strategies: ReadonlyArray<SelectOption>;
  backtests: ReadonlyArray<SelectOption>;
  onCancel: () => void;
  onSaved: (noteId: string) => void;
};

/** 创建与编辑共用的表单；提交时把字段原样交给接口，正文不做任何改写。 */
export function JournalEditor({
  noteId,
  initial,
  instruments,
  strategies,
  backtests,
  onCancel,
  onSaved,
}: JournalEditorProps) {
  const [draft, setDraft] = useState<JournalDraft>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (patch: Partial<JournalDraft>) => setDraft((current) => ({ ...current, ...patch }));

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (draft.title.trim() === "") {
      setError("记录标题不能为空");
      return;
    }
    if (draft.content.trim() === "") {
      setError("记录内容不能为空");
      return;
    }

    const body: ResearchNoteCreateRequest = {
      type: draft.type,
      title: draft.title,
      content: draft.content,
      tags: parseResearchNoteTags(draft.tags),
      related_instrument_id: draft.instrumentId || null,
      related_strategy_id: draft.strategyId || null,
      related_backtest_id: draft.backtestId || null,
    };

    setSaving(true);
    setError(null);
    try {
      const saved =
        noteId === undefined
          ? await createResearchNote(body)
          : await updateResearchNote(noteId, body);
      onSaved(saved.id);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "研究记录保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{noteId === undefined ? "新建研究记录" : "编辑研究记录"}</CardTitle>
        <CardDescription>
          正文按输入原样保存。关联对象可选；被引用的标的、策略或回测删除后，记录仍会保留。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={submit}>
          <div className="grid gap-4 md:grid-cols-2">
            <SelectField
              id="journal-editor-type"
              label="类型"
              value={draft.type}
              options={RESEARCH_NOTE_TYPE_OPTIONS}
              onChange={(next) => update({ type: next as ResearchNoteType })}
              hint="接口只接受四种固定类型，页面不改写已保存的类型。"
            />
            <Field label="标题" htmlFor="journal-editor-title">
              <input
                id="journal-editor-title"
                className={inputClassName}
                value={draft.title}
                maxLength={256}
                onChange={(event) => update({ title: event.target.value })}
              />
            </Field>
          </div>

          <Field label="正文" htmlFor="journal-editor-content" hint="原样保存，不做摘要或改写。">
            <textarea
              id="journal-editor-content"
              className="min-h-40 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={draft.content}
              onChange={(event) => update({ content: event.target.value })}
            />
          </Field>

          <div className="grid gap-4 md:grid-cols-3">
            <SelectField
              id="journal-editor-instrument"
              label="关联标的"
              value={draft.instrumentId}
              options={[
                { value: "", label: "不关联标的" },
                ...withCurrentOption(
                  instruments,
                  draft.instrumentId,
                  `${draft.instrumentId}（不在当前列表）`,
                ),
              ]}
              onChange={(next) => update({ instrumentId: next })}
            />
            <SelectField
              id="journal-editor-strategy"
              label="关联策略"
              value={draft.strategyId}
              options={[
                { value: "", label: "不关联策略" },
                ...withCurrentOption(
                  strategies,
                  draft.strategyId,
                  `${draft.strategyId}（不在当前列表）`,
                ),
              ]}
              onChange={(next) => update({ strategyId: next })}
            />
            <SelectField
              id="journal-editor-backtest"
              label="关联回测"
              value={draft.backtestId}
              options={[
                { value: "", label: "不关联回测" },
                ...withCurrentOption(
                  backtests,
                  draft.backtestId,
                  `${draft.backtestId}（不在当前列表）`,
                ),
              ]}
              onChange={(next) => update({ backtestId: next })}
            />
          </div>

          <Field label="标签" htmlFor="journal-editor-tags" hint="用逗号或换行分隔，保存前去空、去重。">
            <input
              id="journal-editor-tags"
              className={inputClassName}
              value={draft.tags}
              onChange={(event) => update({ tags: event.target.value })}
            />
          </Field>

          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}

          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={saving}>
              {saving ? "保存中…" : noteId === undefined ? "创建记录" : "保存修改"}
            </Button>
            <Button type="button" variant="outline" onClick={onCancel} disabled={saving}>
              取消
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
