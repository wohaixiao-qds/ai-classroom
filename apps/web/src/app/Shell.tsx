import { Activity, BookOpen, GraduationCap, LibraryBig, Wand2 } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { ThemeSwitcher } from "../components/ThemeSwitcher";
import { cn } from "../lib/utils";

const NAV = [
  { to: "/", label: "学习台", icon: BookOpen, end: true },
  { to: "/courses", label: "课程库", icon: LibraryBig, end: false },
  { to: "/studio", label: "生成中心", icon: Wand2, end: false },
  { to: "/eval", label: "观测", icon: Activity, end: false },
];

/** 全局壳(甲方案·五区制):顶栏导航 学习台/课程库/生成中心/观测;课堂页沉浸不套这层 */
export function Shell() {
  const link = ({ isActive }: { isActive: boolean }) =>
    cn(
      "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
      isActive
        ? "bg-primary/15 font-medium text-primary"
        : "text-muted-foreground hover:bg-accent hover:text-foreground",
    );
  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <header className="flex shrink-0 items-center gap-8 border-b border-border px-6 py-3">
        <span className="flex items-center gap-2 font-bold tracking-wide">
          <span className="flex size-7 items-center justify-center rounded-md bg-primary/15 text-primary">
            <GraduationCap size={16} />
          </span>
          AI 教室
        </span>
        <nav className="flex gap-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} className={link} end={end} viewTransition>
              <Icon size={14} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto">
          <ThemeSwitcher />
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
