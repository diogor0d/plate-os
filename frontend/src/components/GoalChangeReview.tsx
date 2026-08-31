import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Target, X } from "lucide-react";
import { api } from "../lib/api";
import type { GoalTargets } from "../lib/assistant";
import type { UserProfile } from "../lib/types";
import { Button } from "./ui/button";

const rows: { key: keyof GoalTargets; label: string; unit: string }[] = [
  { key: "target_calories", label: "Calories", unit: "kcal" },
  { key: "target_protein_g", label: "Protein", unit: "g" },
  { key: "target_carbs_g", label: "Carbohydrates", unit: "g" },
  { key: "target_fat_g", label: "Fat", unit: "g" },
];

export function GoalChangeReview({
  proposed,
  rationale,
  caveats,
  onDone,
}: {
  proposed: GoalTargets;
  rationale: string;
  caveats: string[];
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => api<UserProfile>("/api/profile") });
  const save = useMutation({
    mutationFn: () => api<UserProfile>("/api/profile", { method: "PUT", body: JSON.stringify(proposed) }),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["profile"] }),
        qc.invalidateQueries({ queryKey: ["daily-summary"] }),
        qc.invalidateQueries({ queryKey: ["analytics"] }),
      ]);
      onDone();
    },
  });

  return (
    <section className="space-y-4 rounded-xl border border-amber-800/50 bg-amber-950/10 p-4" aria-label="Review proposed goals">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Target className="h-4 w-4 text-amber-400" />
            <h3 className="text-sm font-semibold text-zinc-100">Review goal draft</h3>
          </div>
          <p className="mt-1 text-xs text-amber-300/70">Draft only · nothing changes until you save</p>
        </div>
        <Button variant="ghost" size="icon" onClick={onDone} aria-label="Dismiss goal draft"><X className="h-4 w-4" /></Button>
      </div>

      <p className="text-sm leading-relaxed text-zinc-300">{rationale}</p>
      <div className="overflow-hidden rounded-lg border border-zinc-800">
        <div className="grid grid-cols-[1fr_auto_auto] gap-x-4 bg-zinc-900/70 px-3 py-2 text-[10px] uppercase tracking-wider text-zinc-600">
          <span>Daily target</span><span>Current</span><span>Proposed</span>
        </div>
        {rows.map(({ key, label, unit }) => {
          const current = profile.data?.[key];
          const changed = current !== undefined && current !== proposed[key];
          return (
            <div key={key} className="grid grid-cols-[1fr_auto_auto] gap-x-4 border-t border-zinc-800 px-3 py-2.5 text-sm">
              <span className="text-zinc-400">{label}</span>
              <span className="tabular-nums text-zinc-600">{current ?? "..."} {unit}</span>
              <span className={`min-w-24 text-right tabular-nums font-medium ${changed ? "text-amber-300" : "text-zinc-300"}`}>{proposed[key]} {unit}</span>
            </div>
          );
        })}
      </div>
      {caveats.length > 0 && (
        <ul className="space-y-1 text-xs text-zinc-500">
          {caveats.map((caveat) => <li key={caveat}>· {caveat}</li>)}
        </ul>
      )}
      {save.error && <p role="alert" className="text-xs text-red-400">{save.error.message}</p>}
      <div className="flex items-center justify-between gap-3 border-t border-zinc-800 pt-3">
        <p className="text-[11px] text-zinc-600">Goal changes require an online connection and are not queued.</p>
        <Button disabled={!profile.data || !navigator.onLine || save.isPending} onClick={() => save.mutate()}>
          <Check className="h-4 w-4" /> {save.isPending ? "Saving..." : "Save goals"}
        </Button>
      </div>
    </section>
  );
}
