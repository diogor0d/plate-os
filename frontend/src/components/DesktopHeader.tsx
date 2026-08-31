import { LogOut } from "lucide-react";
import type { ReactNode } from "react";
import type { DailySummary, MeInfo } from "../lib/types";
import { cn } from "../lib/utils";
import { TABS, type Tab } from "./BottomNav";

export function DesktopHeader({
  tab,
  onTab,
  me,
  onLogout,
  summary,
  status,
}: {
  tab: Tab;
  onTab: (tab: Tab) => void;
  me: MeInfo | undefined;
  onLogout: () => void;
  summary: DailySummary | undefined;
  status: ReactNode;
}) {
  const calorieTarget = summary?.targets.calories ?? 0;
  const calorieProgress = calorieTarget > 0
    ? Math.min(100, ((summary?.consumed.calories ?? 0) / calorieTarget) * 100)
    : 0;
  const today = new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(new Date());

  return (
    <header className="sticky top-0 z-20 hidden border-b border-zinc-800/80 bg-zinc-950/90 backdrop-blur-xl md:block">
      <div className="mx-auto grid h-[76px] max-w-7xl grid-cols-[1fr_auto_1fr] items-center gap-5 px-6 lg:px-10">
        <div className="flex min-w-0 items-center gap-3">
          <img src="/logo.svg" alt="" className="h-9 w-9" />
          <div className="min-w-0">
            <p className="text-sm font-semibold tracking-tight text-zinc-100">PlateOS</p>
            <p className="truncate text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-600">
              {today}
            </p>
          </div>
        </div>

        <nav aria-label="Primary" className="flex items-center rounded-xl border border-zinc-800 bg-zinc-900/60 p-1">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => onTab(id)}
              aria-current={tab === id ? "page" : undefined}
              className={cn(
                "flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/70 lg:px-4",
                tab === id
                  ? "bg-zinc-800 text-zinc-50 shadow-sm"
                  : "text-zinc-500 hover:bg-zinc-800/60 hover:text-zinc-200",
              )}
            >
              <Icon className={cn("h-4 w-4", tab === id && "text-emerald-400")} />
              <span className="hidden lg:inline">{label}</span>
            </button>
          ))}
        </nav>

        <div className="flex min-w-0 items-center justify-end gap-3">
          <div className="hidden min-w-0 text-right xl:block">
            {status ?? (
              <p className="truncate text-xs text-zinc-500">
                {me?.is_admin ? "Household admin" : "Household member"}
              </p>
            )}
          </div>
          <div className="flex items-center rounded-xl border border-zinc-800 bg-zinc-900/40 p-1 pl-1.5">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 text-[10px] font-semibold uppercase text-emerald-300">
              {(me?.username ?? "?").slice(0, 2)}
            </span>
            <span className="hidden max-w-24 truncate px-2 text-xs text-zinc-300 lg:block">
              {me?.username ?? "..."}
            </span>
            <button
              type="button"
              onClick={onLogout}
              aria-label="Log out"
              className="rounded-lg p-2 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/70"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      <div className="absolute inset-x-0 bottom-[-1px] h-px bg-zinc-800" aria-hidden="true">
        <div
          className="h-full bg-emerald-400/80 transition-[width] duration-500"
          style={{ width: `${calorieProgress}%` }}
        />
      </div>
      <span className="sr-only">
        {Math.round(calorieProgress)} percent of today's calorie target consumed
      </span>
    </header>
  );
}
