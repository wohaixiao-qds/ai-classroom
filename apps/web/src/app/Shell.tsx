import { Activity, GraduationCap, Wand2 } from "lucide-react";
import type { CSSProperties } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { cn } from "../lib/utils";

const NAV = [
  { to: "/courses", label: "学习", icon: GraduationCap },
  { to: "/studio", label: "生成中心", icon: Wand2 },
  { to: "/eval", label: "观测", icon: Activity },
];

export function Shell() {
  const { pathname } = useLocation();
  const onBookPage = pathname.startsWith("/books/");
  const activeIndex = NAV.findIndex(({ to }) => pathname === to || pathname.startsWith(`${to}/`));
  const selectedIndex = onBookPage ? 0 : activeIndex;

  return (
    <div className="flex h-full flex-col bg-background text-foreground lg:flex-row">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded-md focus:bg-card focus:p-3">
        跳到正文
      </a>
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-x-3 border-b border-border bg-secondary/50 px-4 pt-2 lg:w-52 lg:flex-col lg:flex-nowrap lg:items-stretch lg:justify-start lg:gap-8 lg:border-r lg:border-b-0 lg:p-5">
        <Link to="/courses" viewTransition className="flex min-h-11 w-fit items-center gap-2 rounded-md font-semibold">
          <span className="grid size-8 place-items-center rounded-lg bg-primary/12 text-primary">
            <GraduationCap size={18} aria-hidden="true" />
          </span>
          AI 教室
        </Link>
        <nav aria-label="主导航" className="shell-nav relative order-last grid w-full grid-cols-3 gap-1 pb-2 lg:order-none lg:grid-cols-1 lg:pb-0">
          {selectedIndex >= 0 && (
            <span
              aria-hidden="true"
              className="shell-nav-indicator pointer-events-none absolute inset-x-0 top-0 hidden rounded-lg bg-primary/12 lg:block"
              style={{ "--nav-index": selectedIndex } as CSSProperties}
            />
          )}
          {NAV.map(({ to, label, icon: Icon }, index) => {
            const current = pathname === to;
            const active = index === selectedIndex;
            return (
              <Link
                key={to}
                to={to}
                viewTransition
                aria-current={current ? "page" : active ? "location" : undefined}
                className={cn(
                  "relative flex min-h-11 items-center justify-center gap-2 rounded-lg px-2 text-sm font-medium transition-colors lg:justify-start lg:px-3",
                  active ? "bg-primary/12 text-primary lg:bg-transparent" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <Icon size={16} aria-hidden="true" />
                {label}
              </Link>
            );
          })}
        </nav>
      </header>
      <main id="main-content" tabIndex={-1} className="route-content min-h-0 min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
