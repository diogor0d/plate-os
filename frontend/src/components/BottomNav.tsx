import { BarChart3, Home, MessageCircle, ScanLine } from "lucide-react";
import { cn } from "../lib/utils";

export type Tab = "today" | "scan" | "coach" | "stats";

const TABS = [
  { id: "today", label: "Today", icon: Home },
  { id: "scan", label: "Scan", icon: ScanLine },
  { id: "coach", label: "Coach", icon: MessageCircle },
  { id: "stats", label: "Stats", icon: BarChart3 },
] as const satisfies { id: Tab; label: string; icon: typeof Home }[];

export function BottomNav({ tab, onTab }: { tab: Tab; onTab: (t: Tab) => void }) {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-10 border-t border-zinc-800 bg-zinc-950/95 backdrop-blur pb-safe">
      <div className="mx-auto grid max-w-md grid-cols-4">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => onTab(id)}
            className={cn(
              "flex flex-col items-center gap-1 py-2 text-[10px]",
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
