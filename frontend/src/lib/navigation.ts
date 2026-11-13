import type { LucideIcon } from "lucide-react";

/** 主导航项的纯数据部分；图标留在外壳组件里，便于单独测试路径匹配。 */
export type NavTarget = {
  to: string;
  label: string;
  end?: boolean;
  /** 同一个导航区块下、但路径不在 `to` 之下的旧页面，例如回测详情。 */
  alsoMatch?: string[];
};

export type NavItem = NavTarget & { icon: LucideIcon };

function matchesPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

/** 导航项是否属于当前路径；`alsoMatch` 让回测详情仍高亮「策略与回测」。 */
export function isNavActive(item: NavTarget, pathname: string): boolean {
  if (item.end) return pathname === item.to;
  if (matchesPrefix(pathname, item.to)) return true;
  return (item.alsoMatch ?? []).some((prefix) => matchesPrefix(pathname, prefix));
}

/** 顶栏当前区块名：按主导航匹配；未知路径回退到概览，与路由的通配重定向一致。 */
export function currentSection(pathname: string, items: NavTarget[]): string {
  const matched = items
    .filter((item) => isNavActive(item, pathname))
    .sort((left, right) => right.to.length - left.to.length)[0];
  return matched?.label ?? "概览";
}
