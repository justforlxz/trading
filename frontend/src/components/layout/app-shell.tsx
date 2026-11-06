import type { LucideIcon } from "lucide-react";
import { LayoutDashboard, Layers, Network, Settings2 } from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { cn } from "../../lib/utils";
import { ThemeToggle } from "./theme-toggle";

type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
};

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "概览", icon: LayoutDashboard, end: true },
  { to: "/research", label: "研究", icon: Network },
  { to: "/strategies", label: "策略", icon: Layers },
  { to: "/settings", label: "设置", icon: Settings2 },
];

function currentSection(pathname: string): string {
  const matched = NAV_ITEMS.filter((item) =>
    item.end ? pathname === item.to : pathname.startsWith(item.to),
  ).at(-1);
  return matched?.label ?? "概览";
}

export function AppShell() {
  const { pathname } = useLocation();

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 z-30 flex w-60 flex-col border-r bg-card/60 backdrop-blur">
        <div className="flex h-14 items-center gap-2 px-6">
          <span className="h-2 w-2 rounded-full bg-foreground" />
          <span className="text-[15px] font-semibold tracking-tight">trading</span>
        </div>

        <nav aria-label="主导航" className="flex-1 space-y-1 px-3 py-4">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-accent font-medium text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                )
              }
            >
              <item.icon className="h-4 w-4" aria-hidden="true" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t px-6 py-4 text-xs text-muted-foreground">
          P1 交易前准备 · v0.1.0
        </div>
      </aside>

      <div className="pl-60">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b bg-background/80 px-8 backdrop-blur">
          <span className="text-sm text-muted-foreground">{currentSection(pathname)}</span>
          <ThemeToggle />
        </header>

        <main className="mx-auto w-full max-w-[1160px] px-8 py-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
