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
        description="外观与运行参数。密钥只经环境变量注入，不落库、不进前端。"
      />

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
    </>
  );
}
