import { useEffect, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { fetchMarketEvents, fetchNews } from "../../lib/api";
import { formatBeijingTime } from "../../lib/display";
import {
  collectMarketEvents,
  eventGroup,
  eventGroupLabel,
  eventTypeLabel,
  eventsForTicker,
  type EventGroup,
  type MarketEvent,
  type NewsArticle,
} from "../../lib/market";

const EVENT_GROUPS: EventGroup[] = ["macro", "earnings", "announcement", "other"];

export type EventsCardBodyProps = {
  ticker: string | null;
  events: MarketEvent[];
  news: NewsArticle[];
  eventsError: string | null;
  newsError: string | null;
  loading: boolean;
};

function EventRow({ event }: { event: MarketEvent }) {
  const values = [
    event.forecast === null ? null : `预期 ${event.forecast}`,
    event.previous === null ? null : `前值 ${event.previous}`,
    event.actual === null ? null : `实际 ${event.actual}`,
  ].filter((value): value is string => value !== null);
  return (
    <li className="border-b border-border/60 py-2 last:border-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">{event.title}</p>
          <p className="text-[11px] text-muted-foreground">
            {eventTypeLabel(event.event_type)} · {event.scheduled_at_beijing}
            {event.region ? ` · ${event.region}` : ""}
            {event.ticker ? ` · ${event.ticker}` : ""}
          </p>
        </div>
        {event.importance ? (
          <span className="shrink-0 text-[11px] text-muted-foreground">
            重要度 {event.importance}
          </span>
        ) : null}
      </div>
      {values.length > 0 ? (
        <p className="mt-1 text-[11px] text-muted-foreground">{values.join(" · ")}</p>
      ) : null}
      <p className="mt-1 text-[11px] text-muted-foreground">
        来源：
        {event.source_url ? (
          <a
            href={event.source_url}
            target="_blank"
            rel="noreferrer"
            className="text-primary underline-offset-4 hover:underline"
          >
            {event.source}
          </a>
        ) : (
          event.source
        )}
      </p>
    </li>
  );
}

function NewsRow({ item }: { item: NewsArticle }) {
  return (
    <li className="border-b border-border/60 py-2 last:border-0">
      <p className="text-sm font-medium">
        {item.url ? (
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="text-primary underline-offset-4 hover:underline"
          >
            {item.title}
          </a>
        ) : (
          item.title
        )}
      </p>
      <p className="text-[11px] text-muted-foreground">
        {item.publisher ? `${item.publisher} · ` : ""}来源 {item.source} ·{' '}
        {item.published_at ? formatBeijingTime(item.published_at) : "无发布时间"}
      </p>
      {item.summary ? (
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.summary}</p>
      ) : null}
    </li>
  );
}

/** 详情页近期事件的内容区：只展示接口已采集的事件与新闻，按类型分区。 */
export function EventsCardBody({
  ticker,
  events,
  news,
  eventsError,
  newsError,
  loading,
}: EventsCardBodyProps) {
  if (ticker === null) {
    return (
      <p className="text-sm text-muted-foreground">
        无法确定标的代码，未查询事件与新闻。
      </p>
    );
  }
  if (loading) {
    return <p className="text-sm text-muted-foreground">正在加载事件与新闻…</p>;
  }
  const hasAny = events.length > 0 || news.length > 0;
  return (
    <div className="space-y-4">
      {eventsError ? (
        <p role="alert" className="text-sm text-destructive">
          {eventsError}
        </p>
      ) : null}
      {newsError ? (
        <p role="alert" className="text-sm text-destructive">
          {newsError}
        </p>
      ) : null}
      {!hasAny && !eventsError && !newsError ? (
        <p className="text-sm text-muted-foreground">
          当前没有已采集的宏观、财报、公告或新闻。
        </p>
      ) : null}
      {EVENT_GROUPS.map((group) => {
        const groupEvents = events.filter((event) => eventGroup(event.event_type) === group);
        const showNews = group === "announcement" && news.length > 0;
        if (groupEvents.length === 0 && !showNews) return null;
        return (
          <section key={group} aria-label={eventGroupLabel(group)}>
            <h4 className="text-xs font-medium text-muted-foreground">
              {eventGroupLabel(group)}
            </h4>
            <ul className="mt-1">
              {groupEvents.map((event) => (
                <EventRow key={event.id} event={event} />
              ))}
              {showNews
                ? news.map((item) => <NewsRow key={item.id} item={item} />)
                : null}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : "读取事件失败";
}

/**
 * 详情页近期事件卡：按当前标的的产品代码读取宏观、财报、公告与新闻。
 * 时间、来源与链接全部来自接口，不在页面推断事件内容。
 */
export function InstrumentEventsCard({ ticker }: { ticker: string | null }) {
  const [events, setEvents] = useState<MarketEvent[]>([]);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [newsError, setNewsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(ticker !== null);

  useEffect(() => {
    setEvents([]);
    setNews([]);
    setEventsError(null);
    setNewsError(null);
    if (ticker === null) {
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    Promise.allSettled([
      fetchMarketEvents(ticker, 500),
      fetchMarketEvents(undefined, 500),
      fetchNews(ticker),
    ])
      .then(([tickerEvents, globalEvents, newsResult]) => {
        if (!active) return;
        const { events: mergedEvents, failures } = collectMarketEvents([
          tickerEvents,
          globalEvents,
        ]);
        setEvents(eventsForTicker(mergedEvents, ticker));
        if (failures.length > 0) {
          setEventsError(
            [...new Set(failures.map(messageOf))].join("；"),
          );
        } else {
          setEventsError(null);
        }
        if (newsResult.status === "fulfilled") {
          setNews(newsResult.value.items);
        } else {
          setNewsError(messageOf(newsResult.reason));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [ticker]);

  return (
    <Card data-section="instrument-events">
      <CardHeader className="pb-3">
        <CardTitle>近期事件</CardTitle>
        <CardDescription>
          宏观、财报、公告与新闻来自已采集数据；事件时间按北京时间显示。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <EventsCardBody
          ticker={ticker}
          events={events}
          news={news}
          eventsError={eventsError}
          newsError={newsError}
          loading={loading}
        />
      </CardContent>
    </Card>
  );
}
