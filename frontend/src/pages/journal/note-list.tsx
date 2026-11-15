import { Link } from "react-router-dom";

import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { formatBeijingTime } from "../../lib/display";
import {
  RESEARCH_NOTE_TYPE_OPTIONS,
  countResearchNotesByType,
  researchNoteTypeLabel,
  type ResearchNoteItem,
  type ResearchNoteType,
} from "../../lib/journal";
import { cn } from "../../lib/utils";

const TYPE_TONES: Record<ResearchNoteType, string> = {
  hypothesis: "border-sky-600/40 text-sky-700 dark:text-sky-300",
  backtest_conclusion: "border-violet-600/40 text-violet-700 dark:text-violet-300",
  decision: "border-amber-600/40 text-amber-700 dark:text-amber-300",
  review: "border-emerald-600/40 text-emerald-700 dark:text-emerald-300",
};

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-mono text-2xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

/** 类型数量来自当前筛选返回的记录；不推测、不补造未返回的记录。 */
export function JournalStats({
  items,
  truncated,
}: {
  items: ReadonlyArray<ResearchNoteItem>;
  truncated: boolean;
}) {
  const counts = countResearchNotesByType(items);

  return (
    <Card>
      <CardHeader>
        <CardTitle>数量统计</CardTitle>
        <CardDescription>
          按当前筛选实际返回的记录计数，四种类型之和等于列表条数。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-3 xl:grid-cols-5">
          <Stat label="全部" value={items.length} />
          {RESEARCH_NOTE_TYPE_OPTIONS.map((option) => (
            <Stat key={option.value} label={option.label} value={counts[option.value]} />
          ))}
        </dl>
        {truncated ? (
          <p className="mt-3 text-xs text-destructive">
            记录超过单次自动加载上限，统计只覆盖已加载的记录。请缩小筛选范围后再查看。
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ReferenceLink({ to, children }: { to: string; children: string }) {
  return (
    <Link className="underline-offset-4 hover:underline" to={to}>
      {children}
    </Link>
  );
}

function NoteReferences({ note }: { note: ResearchNoteItem }) {
  return (
    <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
      <div className="flex gap-1">
        <dt>标的</dt>
        <dd>
          {note.related_instrument_id ? (
            <ReferenceLink to={`/watchlist/${encodeURIComponent(note.related_instrument_id)}`}>
              {note.related_instrument_id}
            </ReferenceLink>
          ) : (
            "未关联"
          )}
        </dd>
      </div>
      <div className="flex gap-1">
        <dt>策略</dt>
        <dd>
          {note.related_strategy_id ? (
            <ReferenceLink to={`/strategies?strategy=${encodeURIComponent(note.related_strategy_id)}`}>
              {note.related_strategy_id}
            </ReferenceLink>
          ) : (
            "未关联"
          )}
        </dd>
      </div>
      <div className="flex gap-1">
        <dt>回测</dt>
        <dd>
          {note.related_backtest_id ? (
            <ReferenceLink to={`/backtests?run=${encodeURIComponent(note.related_backtest_id)}`}>
              {note.related_backtest_id}
            </ReferenceLink>
          ) : (
            "未关联"
          )}
        </dd>
      </div>
    </dl>
  );
}

export type ResearchNoteListProps = {
  items: ReadonlyArray<ResearchNoteItem>;
  loading: boolean;
  onEdit: (note: ResearchNoteItem) => void;
  onDelete: (note: ResearchNoteItem) => void;
};

export function ResearchNoteList({ items, loading, onEdit, onDelete }: ResearchNoteListProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <CardTitle>研究记录</CardTitle>
          <span className="text-xs text-muted-foreground">本页 {items.length} 条</span>
        </div>
        <CardDescription>正文按用户写入的原样展示，页面不做改写或摘要。</CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <p className="text-sm text-muted-foreground">正在加载研究记录…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">当前筛选没有研究记录。</p>
        ) : (
          <ul className="space-y-4">
            {items.map((note) => (
              <li key={note.id} className="rounded-lg border p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-xs",
                          TYPE_TONES[note.type],
                        )}
                      >
                        {researchNoteTypeLabel(note.type)}
                      </span>
                      <h3 className="break-words text-sm font-semibold">{note.title}</h3>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      创建 {formatBeijingTime(note.created_at)} · 更新{" "}
                      {formatBeijingTime(note.updated_at)} · <span className="font-mono">{note.id}</span>
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button type="button" variant="outline" size="sm" onClick={() => onEdit(note)}>
                      编辑
                    </Button>
                    <Button type="button" variant="ghost" size="sm" onClick={() => onDelete(note)}>
                      删除
                    </Button>
                  </div>
                </div>

                {note.tags.length > 0 ? (
                  <ul className="mt-3 flex flex-wrap gap-1.5">
                    {note.tags.map((tag) => (
                      <li
                        key={tag}
                        className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                      >
                        {tag}
                      </li>
                    ))}
                  </ul>
                ) : null}

                <NoteReferences note={note} />

                <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6">
                  {note.content}
                </p>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
