import {
  Layers,
  LayoutDashboard,
  Menu,
  NotebookPen,
  Settings2,
  Star,
  Wallet,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { fetchHealth } from "../../lib/api";
import { currentSection, isNavActive, type NavItem } from "../../lib/navigation";
import { cn } from "../../lib/utils";
import { Button } from "../ui/button";
import { ThemeToggle } from "./theme-toggle";

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "概览", icon: LayoutDashboard, end: true },
  { to: "/watchlist", label: "自选", icon: Star },
  { to: "/positions", label: "持仓", icon: Wallet },
  { to: "/strategies", label: "策略与回测", icon: Layers, alsoMatch: ["/backtests"] },
  { to: "/journal", label: "记录", icon: NotebookPen },
  { to: "/settings", label: "设置", icon: Settings2 },
];

const HEALTH_POLL_MS = 30_000;

/** 顶栏的数据连接状态来自真实健康检查；未知或失败一律显示「未连接」。 */
function useDataConnection(): boolean {
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;

    const check = async () => {
      try {
        const health = await fetchHealth();
        if (active) setConnected(health.status === "ok");
      } catch {
        if (active) setConnected(false);
      }
      if (active) timer = window.setTimeout(() => void check(), HEALTH_POLL_MS);
    };

    void check();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  return connected;
}

const NAV_LINK_CLASS =
  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function AppShell() {
  const { pathname } = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const connected = useDataConnection();
  const section = currentSection(pathname, NAV_ITEMS);

  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  return (
    <div className="min-h-screen overflow-x-hidden bg-background">
      {drawerOpen ? (
        <div
          role="presentation"
          className="fixed inset-0 z-30 bg-foreground/20 backdrop-blur-[1px] min-[1081px]:hidden"
          onClick={() => setDrawerOpen(false)}
        />
      ) : null}

      <aside
        id="app-sidebar"
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r bg-card/60 backdrop-blur transition-transform duration-200 ease-out",
          drawerOpen ? "translate-x-0" : "-translate-x-full",
          "min-[1081px]:translate-x-0",
        )}
      >
        <div className="flex h-14 items-center justify-between gap-2 px-6">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-foreground" />
            <span className="text-[15px] font-semibold tracking-tight">trading</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="min-[1081px]:hidden"
            aria-label="关闭导航菜单"
            onClick={() => setDrawerOpen(false)}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>

        <nav aria-label="主导航" className="flex-1 space-y-1 px-3 py-4">
          {NAV_ITEMS.map((item) => {
            const active = isNavActive(item, pathname);
            return (
              <Link
                key={item.to}
                to={item.to}
                aria-current={active ? "page" : undefined}
                onClick={() => setDrawerOpen(false)}
                className={cn(
                  NAV_LINK_CLASS,
                  active
                    ? "bg-accent font-medium text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                )}
              >
                <item.icon className="h-4 w-4" aria-hidden="true" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t px-6 py-4 text-xs text-muted-foreground">v6 骨架 · v0.2.0</div>
      </aside>

      <div className="min-[1081px]:pl-60">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b bg-background/80 px-8 backdrop-blur max-[640px]:px-4">
          <div className="flex min-w-0 items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="min-[1081px]:hidden"
              aria-label={drawerOpen ? "关闭导航菜单" : "打开导航菜单"}
              aria-expanded={drawerOpen}
              aria-controls="app-sidebar"
              onClick={() => setDrawerOpen((open) => !open)}
            >
              {drawerOpen ? (
                <X className="h-4 w-4" aria-hidden="true" />
              ) : (
                <Menu className="h-4 w-4" aria-hidden="true" />
              )}
            </Button>
            <span className="truncate text-sm text-muted-foreground">{section}</span>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span
              className="inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs text-muted-foreground"
              aria-live="polite"
              title={connected ? "后端健康检查正常" : "后端健康检查不可用"}
              data-testid="data-connection"
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  connected ? "bg-emerald-500" : "bg-muted-foreground",
                )}
                aria-hidden="true"
              />
              {connected ? "已连接" : "未连接"}
            </span>
            <ThemeToggle />
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1160px] px-8 py-10 pb-16 max-[640px]:px-4 max-[640px]:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
