import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeading } from "../components/layout/page-parts";
import { Button } from "../components/ui/button";
import {
  deleteResearchNote,
  fetchBacktests,
  fetchResearchNotes,
  fetchStrategies,
  fetchTradableInstruments,
  type BacktestRunListResponse,
  type ResearchNoteItem,
} from "../lib/api";
import {
  researchNoteType,
  type ResearchNoteFilters,
} from "../lib/journal";
import { BACKTEST_DATA_SOURCE_OPTIONS } from "../lib/strategies";
import {
  draftFromNote,
  emptyJournalDraft,
  type JournalDraft,
  type SelectOption,
} from "./journal/fields";
import { JournalFilters } from "./journal/filters";
import { JournalEditor } from "./journal/note-editor";
import { JournalStats, ResearchNoteList } from "./journal/note-list";

const PAGE_SIZE = 200;
const MAX_PAGES = 20;

const DEFAULT_FILTERS: ResearchNoteFilters = { sort: "created_at_desc" };

type ReferenceOptions = {
  instruments: SelectOption[];
  strategies: SelectOption[];
  backtests: SelectOption[];
};

type EditorState = {
  key: string;
  noteId?: string;
  draft: JournalDraft;
};

/**
 * 接口没有单独的统计端点，因此按同一筛选条件逐页取回记录后再计数。
 * 计数只覆盖接口实际返回的记录；超过上限会明确提示，不推测剩余数量。
 */
async function loadAllNotes(
  filters: ResearchNoteFilters,
): Promise<{ items: ResearchNoteItem[]; truncated: boolean }> {
  const items: ResearchNoteItem[] = [];
  let cursor: string | undefined;

  for (let page = 0; page < MAX_PAGES; page += 1) {
    const response = await fetchResearchNotes(filters, PAGE_SIZE, cursor);
    items.push(...response.items);
    const next = response.next_cursor ?? null;
    if (next === null || next === cursor) return { items, truncated: false };
    cursor = next;
  }

  return { items, truncated: true };
}

function instrumentOptions(
  spot: ReadonlyArray<{ inst_id: string; inst_type: "SPOT" | "SWAP" }> | null,
  swap: ReadonlyArray<{ inst_id: string; inst_type: "SPOT" | "SWAP" }> | null,
): SelectOption[] {
  const seen = new Set<string>();
  const options: SelectOption[] = [];
  for (const instrument of [...(spot ?? []), ...(swap ?? [])]) {
    if (seen.has(instrument.inst_id)) continue;
    seen.add(instrument.inst_id);
    options.push({
      value: instrument.inst_id,
      label: `${instrument.inst_id}（${instrument.inst_type === "SWAP" ? "永续" : "现货"}）`,
    });
  }
  return options.sort((left, right) => left.value.localeCompare(right.value));
}

function backtestOptions(results: ReadonlyArray<BacktestRunListResponse | null>): SelectOption[] {
  const rows = results.flatMap((result) => result?.items ?? []);
  return rows
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .map((run) => ({
      value: run.run_id,
      label: `${run.run_id} · ${run.data_source} · ${run.inst_id} · ${run.start_date}~${run.end_date}`,
    }));
}

/**
 * 记录页：四种研究记录的创建、编辑、删除、筛选、排序与关联。
 *
 * 筛选条件、排序和正文都交给接口；页面只把返回值按原样展示，不做摘要、改写或
 * 前端的二次业务过滤。关联对象点击后进入对应页面。
 */
export default function JournalPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [filters, setFilters] = useState<ResearchNoteFilters>(DEFAULT_FILTERS);
  const [items, setItems] = useState<ResearchNoteItem[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [referenceError, setReferenceError] = useState<string | null>(null);
  const [references, setReferences] = useState<ReferenceOptions>({
    instruments: [],
    strategies: [],
    backtests: [],
  });
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const deepLinkHandled = useRef(false);

  useEffect(() => {
    let active = true;

    async function loadReferences(): Promise<void> {
      const [spot, swap, strategyList, ...backtestLists] = await Promise.all([
        fetchTradableInstruments("SPOT").catch(() => null),
        fetchTradableInstruments("SWAP").catch(() => null),
        fetchStrategies().catch(() => null),
        ...BACKTEST_DATA_SOURCE_OPTIONS.map((option) =>
          fetchBacktests(option.value, PAGE_SIZE).catch(() => null),
        ),
      ]);
      if (!active) return;

      const failed = spot === null || swap === null || strategyList === null;
      setReferenceError(
        failed ? "部分关联对象列表加载失败，仍可按类型、时间与已有标识筛选。" : null,
      );
      setReferences({
        instruments: instrumentOptions(spot?.items ?? null, swap?.items ?? null),
        strategies: (strategyList?.items ?? [])
          .map((item) => ({ value: item.id, label: `${item.name}（${item.id}）` }))
          .sort((left, right) => left.label.localeCompare(right.label)),
        backtests: backtestOptions(backtestLists),
      });
    }

    void loadReferences();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (deepLinkHandled.current) return;
    if (searchParams.get("new") === null) return;
    deepLinkHandled.current = true;
    const type = researchNoteType(searchParams.get("type")) ?? "review";
    const backtestId = searchParams.get("backtest") ?? "";
    setEditor({ key: `deep-link-${Date.now()}`, draft: emptyJournalDraft(type, backtestId) });
    setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    loadAllNotes(filters)
      .then((result) => {
        if (!active) return;
        setItems(result.items);
        setTruncated(result.truncated);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "研究记录加载失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [filters, refreshToken]);

  const reload = () => setRefreshToken((current) => current + 1);

  const remove = async (note: ResearchNoteItem): Promise<void> => {
    if (!window.confirm(`删除研究记录「${note.title}」？此操作不可撤销。`)) return;
    setError(null);
    try {
      await deleteResearchNote(note.id);
      if (editor?.noteId === note.id) setEditor(null);
      reload();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "研究记录删除失败");
    }
  };

  return (
    <>
      <PageHeading
        eyebrow="Journal"
        title="记录"
        description="保存研究假设、回测结论、决策与复盘，并把每条记录关联到标的、策略或回测。正文原样展示，不做改写或摘要。"
        actions={
          <Button
            type="button"
            onClick={() => setEditor({ key: `create-${Date.now()}`, draft: emptyJournalDraft() })}
          >
            新建记录
          </Button>
        }
      />

      {error ? (
        <p
          role="alert"
          className="mb-6 rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive"
        >
          {error}
        </p>
      ) : null}

      {referenceError ? (
        <p className="mb-6 rounded-md border px-3 py-2 text-sm text-muted-foreground">
          {referenceError}
        </p>
      ) : null}

      <div className="grid gap-6">
        {editor ? (
          <JournalEditor
            key={editor.key}
            noteId={editor.noteId}
            initial={editor.draft}
            instruments={references.instruments}
            strategies={references.strategies}
            backtests={references.backtests}
            onCancel={() => setEditor(null)}
            onSaved={() => {
              setEditor(null);
              reload();
            }}
          />
        ) : null}

        <JournalStats items={items} truncated={truncated} />

        <JournalFilters
          value={filters}
          instruments={references.instruments}
          strategies={references.strategies}
          backtests={references.backtests}
          onChange={setFilters}
          onReset={() => setFilters(DEFAULT_FILTERS)}
        />

        <ResearchNoteList
          items={items}
          loading={loading}
          onEdit={(note) =>
            setEditor({
              key: `edit-${note.id}`,
              noteId: note.id,
              draft: draftFromNote(note),
            })
          }
          onDelete={(note) => {
            void remove(note);
          }}
        />
      </div>
    </>
  );
}
