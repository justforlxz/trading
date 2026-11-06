import { Monitor, Moon, Sun } from "lucide-react";

import { PageHeading } from "../components/layout/page-parts";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { useTheme, type ThemeMode } from "../lib/theme";

const OPTIONS: { mode: ThemeMode; label: string; icon: typeof Sun }[] = [
  { mode: "system", label: "跟随系统", icon: Monitor },
  { mode: "light", label: "浅色", icon: Sun },
  { mode: "dark", label: "深色", icon: Moon },
];

export default function SettingsPage() {
  const { mode, setMode } = useTheme();

  return (
    <>
      <PageHeading
        eyebrow="Settings"
        title="设置"
        description="外观、行情源与系统参数。行情源与标的过滤规则在 S3 依据外部依赖核查结论落地，此页面当前只承载可用的本地外观设置。"
      />

      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <CardTitle>外观</CardTitle>
            <CardDescription>
              默认跟随系统配色，手动选择后写入本地存储并在刷新后保持。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="inline-flex rounded-md border p-1" role="group" aria-label="主题模式">
              {OPTIONS.map((option) => {
                const active = mode === option.mode;
                return (
                  <Button
                    key={option.mode}
                    variant={active ? "secondary" : "ghost"}
                    size="sm"
                    aria-pressed={active}
                    onClick={() => setMode(option.mode)}
                    className="gap-2"
                  >
                    <option.icon className="h-4 w-4" aria-hidden="true" />
                    {option.label}
                  </Button>
                );
              })}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-4">
              <CardTitle>行情源与系统参数</CardTitle>
              <span className="shrink-0 rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground">
                S3
              </span>
            </div>
            <CardDescription>
              S3 起接入：数据来源台账、同步状态与采集参数；密钥只经环境变量注入，不落库、不入前端。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-x-8 gap-y-2 text-sm text-muted-foreground sm:grid-cols-2">
              {["行情源与可回溯范围", "数据来源与抓取时间", "OKX 连接配置", "采集与保留策略"].map(
                (item) => (
                  <li key={item} className="flex items-start gap-2">
                    <span
                      className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/70"
                      aria-hidden="true"
                    />
                    {item}
                  </li>
                ),
              )}
            </ul>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
