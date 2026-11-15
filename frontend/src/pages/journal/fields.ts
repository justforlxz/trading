import { joinResearchNoteTags, type ResearchNoteItem, type ResearchNoteType } from "../../lib/journal";

export type SelectOption = { value: string; label: string };

/** 当前值不在选项里时补一条，避免编辑旧记录时把已有引用悄悄清空。 */
export function withCurrentOption(
  options: ReadonlyArray<SelectOption>,
  current: string | undefined,
  fallbackLabel: string,
): SelectOption[] {
  if (current === undefined || current === "") return [...options];
  if (options.some((option) => option.value === current)) return [...options];
  return [...options, { value: current, label: fallbackLabel }];
}

export const inputClassName =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";

export type JournalDraft = {
  type: ResearchNoteType;
  title: string;
  content: string;
  instrumentId: string;
  strategyId: string;
  backtestId: string;
  tags: string;
};

export function emptyJournalDraft(
  type: ResearchNoteType = "hypothesis",
  backtestId = "",
): JournalDraft {
  return {
    type,
    title: "",
    content: "",
    instrumentId: "",
    strategyId: "",
    backtestId,
    tags: "",
  };
}

export function draftFromNote(note: ResearchNoteItem): JournalDraft {
  return {
    type: note.type,
    title: note.title,
    content: note.content,
    instrumentId: note.related_instrument_id ?? "",
    strategyId: note.related_strategy_id ?? "",
    backtestId: note.related_backtest_id ?? "",
    tags: joinResearchNoteTags(note.tags),
  };
}
