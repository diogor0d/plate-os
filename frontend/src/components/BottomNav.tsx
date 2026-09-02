import { BarChart3, CalendarClock, Home, MessageCircle, ScanLine, Settings } from "lucide-react";
import { cn } from "../lib/utils";

export type Tab = "today" | "scan" | "plan" | "coach" | "stats" | "settings";

export const TABS: readonly {
  id: Tab;
  label: string;
  icon: typeof Home;
}[] = [
  { id: "today", label: "Today", icon: Home },
  { id: "scan", label: "Scan", icon: ScanLine },
  { id: "plan", label: "Plan", icon: CalendarClock },
  { id: "coach", label: "Coach", icon: MessageCircle },
  { id: "stats", label: "Stats", icon: BarChart3 },
  { id: "settings", label: "Settings", icon: Settings },
];

export function BottomNav({ tab, onTab }: { tab: Tab; onTab: (t: Tab) => void }) {
  return (
    <nav
      aria-label="Primary"
      className="z-10 shrink-0 border-t border-zinc-800 bg-zinc-950 pb-safe md:hidden"
    >
      <div className="mx-auto grid max-w-md grid-cols-6">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => onTab(id)}
            aria-current={tab === id ? "page" : undefined}
            className={cn(
              "flex flex-col items-center gap-1 py-2 text-[10px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-500/70",
              tab === id ? "text-emerald-400" : "text-zinc-500",
            )}
          >
            <Icon className="h-5 w-5" />
            {label}
          </button>
        ))}
      </div>
    </nav>
  );
}
