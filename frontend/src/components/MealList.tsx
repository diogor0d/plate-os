import type { MealLog } from "../lib/types";

export function MealList({ logs, onDelete }: { logs: MealLog[] | undefined; onDelete?: (id: string) => void }) {
  if (!logs) return null;
  if (logs.length === 0)
    return <p className="py-6 text-center text-sm text-zinc-500">Nothing logged yet today.</p>;
  return (
    <ul className="divide-y divide-zinc-800">
      {logs.map((log) => (
        <li key={log.id} className="flex items-center justify-between gap-2 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{log.custom_name ?? "Food item"}</p>
            <p className="text-xs text-zinc-500">
              {new Date(log.logged_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} ·{" "}
              {Math.round(log.quantity_g)}g · {log.source_type.replaceAll("_", " ")}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right text-sm">
              <p>{Math.round(log.calculated_calories)} kcal</p>
              <p className="text-xs text-zinc-500">{Math.round(log.calculated_protein)}g P</p>
            </div>
            {onDelete && (
              <button
                onClick={() => onDelete(log.id)}
                className="text-xs text-zinc-600 hover:text-red-400"
                aria-label={`Delete ${log.custom_name ?? "entry"}`}
              >
                ✕
              </button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
