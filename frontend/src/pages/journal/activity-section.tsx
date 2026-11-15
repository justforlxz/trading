import { useEffect, useState } from "react";

import { ActivityTimeline } from "../../components/ui/activity-timeline";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  fetchActivity,
  type ActivityFilters,
  type ActivityItem,
} from "../../lib/api";
import { ACTIVITY_EVENT_OPTIONS } from "../../lib/activity";
import { Field, SelectField } from "./shared";
import { inputClassName } from "./fields";

const PAGE_SIZE = 50;
const DEFAULT_FILTERS: ActivityFilters = {};

function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : "活动流水加载失败";
}

/**
 * 记录页的活动流水：筛选与分页全部交给 `GET /api/activity`。
 * 条目复用首页同一套活动时间线组件，不在这里改写活动文案。
 */
export function JournalActivitySection() {
  const [filters, setFilters] = useState<ActivityFilters>(DEFAULT_FILTERS);
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetchActivity(filters, PAGE_SIZE)
      .then((response) => {
        if (!active) return;
        setItems(response.items);
        setNextCursor(response.next_cursor ?? null);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(messageOf(reason));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [filters, refreshToken]);

  const loadMore = async (): Promise<void> => {
    if (nextCursor === null) return;
    setLoadingMore(true);
    setError(null);
    try {
      const response = await fetchActivity(filters, PAGE_SIZE, nextCursor);
      setItems((current) => [...current, ...response.items]);
      setNextCursor(response.next_cursor ?? null);
    } catch (reason: unknown) {
      setError(messageOf(reason));
    } finally {
      setLoadingMore(false);
    }
  };

  const update = (patch: Partial<ActivityFilters>) => setFilters({ ...filters, ...patch });

  return (
    <Card data-section="journal-activity">
      <CardHeader>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div className="space-y-1">
            <CardTitle>活动流水</CardTitle>
            <CardDescription>
              来自 `GET /api/activity`；按事件类型与北京时间日期筛选，分页读取，不改写活动文案。
            </CardDescription>
          </div>
          <span className="text-xs text-muted-foreground">已加载 {items.length} 条</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-3">
          <SelectField
            id="journal-activity-event-type"
            label="事件类型"
            value={filters.eventType ?? ""}
            options={[{ value: "", label: "全部事件" }, ...ACTIVITY_EVENT_OPTIONS]}
            onChange={(next) => update({ eventType: next === "" ? undefined : next })}
          />
          <Field label="起始日期" htmlFor="journal-activity-from" hint="北京时间，含当天。">
            <input
              id="journal-activity-from"
              type="date"
              className={inputClassName}
              value={filters.from ?? ""}
              onChange={(event) => update({ from: event.target.value || undefined })}
            />
          </Field>
          <Field label="截止日期" htmlFor="journal-activity-to" hint="北京时间，含当天。">
            <input
              id="journal-activity-to"
              type="date"
              className={inputClassName}
              value={filters.to ?? ""}
              onChange={(event) => update({ to: event.target.value || undefined })}
            />
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setRefreshToken((token) => token + 1)}
            disabled={loading}
          >
            {loading ? "刷新中…" : "刷新"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setFilters(DEFAULT_FILTERS)}
            disabled={loading}
          >
            重置筛选
          </Button>
        </div>

        {error ? (
          <p role="alert" className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <ActivityTimeline items={items} loading={loading} emptyText="当前筛选没有活动流水。" />

        {nextCursor !== null ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              void loadMore();
            }}
            disabled={loading || loadingMore}
          >
            {loadingMore ? "加载中…" : "加载更多"}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
