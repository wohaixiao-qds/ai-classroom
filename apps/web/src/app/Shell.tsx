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
    /* 根容器透明:body 的双色 radial 光晕+细颗粒纸纹(design/library.html)全站透出。
       z-[1] 让 Shell 内容浮在纸纹层(body::before, z-0)之上——与设计稿 .wrap z-index:1 同构 */
    <div className="relative z-[1] flex h-full flex-col text-foreground lg:flex-row">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded-md focus:bg-card focus:p-3">
        跳到正文
      </a>
      {/* 导航铬底(.shell-chrome,见 index.css):半透明+blur,分界线两端渐隐(移动端贴底/桌面端贴右) */}
      <header className="shell-chrome flex shrink-0 flex-wrap items-center justify-between gap-x-3 px-4 pt-2 lg:w-52 lg:flex-col lg:flex-nowrap lg:items-stretch lg:justify-start lg:gap-8 lg:p-5">
        <Link to="/courses" viewTransition className="flex min-h-11 w-fit items-center gap-2 rounded-md font-semibold">
          {/* 品牌方块 mark(design/library.html .logo .mark):靛蓝→深靛蓝渐变+顶部高光 */}
          <span className="grid size-8 place-items-center rounded-lg bg-[linear-gradient(135deg,var(--accent),var(--accent-deep))] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.35),0_2px_6px_rgba(70,85,212,0.35)]">
            <GraduationCap size={18} aria-hidden="true" />
          </span>
          AI 教室
        </Link>
        <nav aria-label="主导航" className="shell-nav relative order-last grid w-full grid-cols-3 gap-1 pb-2 lg:order-none lg:grid-cols-1 lg:pb-0">
          {selectedIndex >= 0 && (
            <span
              aria-hidden="true"
              className="shell-nav-indicator pointer-events-none absolute inset-x-0 top-0 hidden rounded-lg bg-card shadow-[var(--shadow-1),inset_0_0_0_1px_var(--line)] lg:block"
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
                  // 激活=白底浮起 pill(design/library.html .nav a.on):移动端直接给条目,
                  // 桌面端交给滑动的 shell-nav-indicator(避免滑动期间双 pill);非激活=灰字 hover 加深
                  active
                    ? "bg-card font-semibold text-foreground shadow-[var(--shadow-1),inset_0_0_0_1px_var(--line)] lg:bg-transparent lg:shadow-none"
                    : "text-muted-foreground hover:text-foreground",
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
