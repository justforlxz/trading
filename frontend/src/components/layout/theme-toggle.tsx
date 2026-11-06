import { Monitor, Moon, Sun } from "lucide-react";

import { Button } from "../ui/button";
import { useTheme, type ThemeMode } from "../../lib/theme";

const NEXT_MODE: Record<ThemeMode, ThemeMode> = {
  system: "light",
  light: "dark",
  dark: "system",
};

const MODE_LABEL: Record<ThemeMode, string> = {
  system: "跟随系统",
  light: "浅色",
  dark: "深色",
};

const MODE_ICON = {
  system: Monitor,
  light: Sun,
  dark: Moon,
} as const;

/** 主题切换：每一次点击在「跟随系统 → 浅色 → 深色」之间循环，选择会持久化。 */
export function ThemeToggle() {
  const { mode, setMode } = useTheme();
  const Icon = MODE_ICON[mode];

  return (
    <Button
      variant="ghost"
      size="sm"
      className="gap-2 text-muted-foreground"
      onClick={() => setMode(NEXT_MODE[mode])}
      aria-label={`切换主题，当前为${MODE_LABEL[mode]}`}
      data-testid="theme-toggle"
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
      <span className="hidden xl:inline">{MODE_LABEL[mode]}</span>
    </Button>
  );
}
