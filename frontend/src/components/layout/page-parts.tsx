import type { ReactNode } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";

export function PageHeading({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          {eyebrow}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>
      </div>
      {actions ? (
        <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">{actions}</div>
      ) : null}
    </div>
  );
}

/**
 * 尚未实现的区域。只说明「按计划会有什么」，不展示任何业务数值，
 * 避免用编造的业务数值伪装功能已完成（项目开发原则）。
 */
export function PendingPanel({
  stage,
  title,
  items,
}: {
  stage: string;
  title: string;
  items: string[];
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <CardTitle>{title}</CardTitle>
          <span className="shrink-0 rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground">
            {stage}
          </span>
        </div>
        <CardDescription>
          骨架阶段只交付布局、导航与主题；本区域按计划在后续节点接入真实数据。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="grid gap-x-8 gap-y-2 sm:grid-cols-2">
          {items.map((item) => (
            <li key={item} className="flex items-start gap-2 text-sm text-muted-foreground">
              <span
                className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/70"
                aria-hidden="true"
              />
              {item}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
