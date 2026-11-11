import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import type { StrategyDefinition } from "../../lib/api";
import { cn } from "../../lib/utils";

/** 一个模板参数的一句话摘要：标题 + 默认值 + 允许区间。 */
function paramSummary(template: StrategyDefinition): string {
  return template.params
    .map((param) => `${param.title} ${param.default}（${param.minimum}–${param.maximum}）`)
    .join(" · ");
}

export type TemplateCatalogProps = {
  templates: StrategyDefinition[];
  selectedId: string | null;
  onSelect: (strategyId: string) => void;
};

/**
 * 组合模板列表。模板来自后端注册表，只读：这里只负责展示与选中，
 * 参数默认值与取值范围一律照抄后端返回的 `ParamSpec`。
 */
export function TemplateCatalog({ templates, selectedId, onSelect }: TemplateCatalogProps) {
  return (
    <Card>
      <CardHeader>
        <div className="space-y-1.5">
          <CardTitle>组合模板</CardTitle>
          <CardDescription>
            模板定义「怎么组合」，只读；选中一个模板再为它建实例。参数默认值与取值范围由后端给出。
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        {templates.length === 0 ? (
          <p className="text-sm text-muted-foreground">后端还没有登记任何组合模板。</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {templates.map((template) => {
              const selected = template.strategy_id === selectedId;
              return (
                <button
                  key={template.strategy_id}
                  type="button"
                  onClick={() => onSelect(template.strategy_id)}
                  aria-pressed={selected}
                  className={cn(
                    "rounded-lg border p-4 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected && "border-primary bg-accent",
                  )}
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-sm font-medium">{template.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {template.strategy_id} · v{template.version}
                    </span>
                  </div>
                  <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
                    {template.summary}
                  </p>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">
                    {paramSummary(template)}
                  </p>
                </button>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
