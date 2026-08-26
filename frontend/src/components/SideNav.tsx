/**
 * Desktop navigation rail (md+): logo, vertical tabs with an emerald active
 * indicator, and the account footer. Mobile keeps BottomNav.
 */
import { LogOut } from "lucide-react";
import { cn } from "../lib/utils";
import type { MeInfo } from "../lib/types";
import { TABS, type Tab } from "./BottomNav";

export function SideNav({
  tab,
  onTab,
  me,
  onLogout,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  me: MeInfo | undefined;
  onLogout: () => void;
}) {
  return (
    <aside className="hidden h-screen w-60 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950/80 md:flex">
      <div className="flex items-center gap-2.5 px-5 pb-6 pt-6">
        <img src="/logo.svg" alt="" className="h-8 w-8" />
        <span className="text-base font-semibold tracking-tight">PlateOS</span>
      </div>

      <nav className="flex-1 space-y-0.5 px-3">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => onTab(id)}
            className={cn(
              "group relative flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
              tab === id
                ? "bg-emerald-500/10 text-emerald-300"
                : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200",
            )}
          >
            {tab === id && (
              <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-emerald-400" />
            )}
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </nav>

      <div className="border-t border-zinc-800 p-3">
        <div className="flex items-center gap-2.5 rounded-lg px-2 py-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-xs font-semibold uppercase text-emerald-300">
            {(me?.username ?? "?").slice(0, 2)}
          </span>
          <span className="min-w-0 flex-1 truncate text-xs text-zinc-400">
            {me?.username ?? "…"}
            {me?.is_admin && (
              <span className="ml-1.5 rounded border border-zinc-700 px-1 py-px text-[9px] uppercase tracking-wide text-zinc-500">
                admin
              </span>
            )}
          </span>
          <button
            onClick={onLogout}
            aria-label="Log out"
            className="rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-zinc-900 hover:text-zinc-300"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
