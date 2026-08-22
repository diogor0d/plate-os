/**
 * The Proposal Card — the enforcement point of the "zero silent database
 * mutations" invariant. Nothing reaches PostgreSQL until the user presses
 * Confirm. Quantity edits recompute totals locally via lib/nutrition (the
 * deterministic mirror of the backend's math).
 */
import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Minus, Plus, X } from "lucide-react";
import { Button } from "./ui/button";
import { ApiError, api } from "../lib/api";
import { scaleToQuantity, sumTotals } from "../lib/nutrition";
import type { MealLogCreate, Per100, SourceType } from "../lib/types";
import { enqueueMealLog } from "../lib/offline/db";

export interface ProposalCardItem {
  name: string;
  per100: Per100;
  quantityG: number;
  confidence?: "high" | "medium" | "low";
  reasoning?: string;
  foodItemId?: string | null;
  sourceType: SourceType;
}

export function ProposalCard({
  items,
  onDone,
}: {
  items: ProposalCardItem[];
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [quantities, setQuantities] = useState<number[]>(() => items.map((i) => i.quantityG));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const totals = useMemo(
    () => sumTotals(items.map((item, idx) => scaleToQuantity(item.per100, quantities[idx]))),
    [items, quantities],
  );

  const step = (idx: number, delta: number) =>
    setQuantities((qs) =>
      qs.map((q, i) => (i === idx ? Math.max(1, Math.round((q + delta) * 10) / 10) : q)),
    );

  const confirm = async () => {
    setSaving(true);
    setError(null);
    try {
      const payloads: MealLogCreate[] = items.map((item, idx) => ({
        food_item_id: item.foodItemId ?? null,
        custom_name: item.name,
        quantity_g: quantities[idx],
        per100: item.foodItemId ? null : item.per100,
        source_type: item.sourceType,
      }));
      for (const payload of payloads) {
        if (navigator.onLine) {
          try {
            await api("/api/meal-logs", { method: "POST", body: JSON.stringify(payload) });
          } catch (err) {
            if (err instanceof ApiError && err.status === 401) throw err;
            await enqueueMealLog(payload); // network hiccup: queue for later
          }
        } else {
          await enqueueMealLog(payload);
        }
      }
      await qc.invalidateQueries();
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3 rounded-xl border border-emerald-900/60 bg-zinc-900/80 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">📝 Review &amp; Log</h3>
        <Button variant="ghost" size="icon" onClick={onDone} aria-label="Dismiss proposal">
          <X className="h-4 w-4" />
        </Button>
      </div>

      {items.map((item, idx) => {
        const itemTotals = scaleToQuantity(item.per100, quantities[idx]);
        return (
          <div key={idx} className="rounded-lg bg-zinc-950/60 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{item.name}</p>
                <p className="text-xs text-zinc-500">
                  {Math.round(itemTotals.calories)} kcal · {Math.round(itemTotals.protein_g)}g P
                  {item.confidence ? ` · ${item.confidence} confidence` : ""}
                </p>
              </div>
              <div className="stepper flex shrink-0 items-center gap-1">
                <Button variant="outline" size="sm" onClick={() => step(idx, -10)} aria-label="Decrease 10g">
                  <Minus className="h-3 w-3" />
                </Button>
                <input
                  type="number"
                  inputMode="decimal"
                  className="w-16 bg-transparent text-center text-sm"
                  value={quantities[idx]}
                  onChange={(e) =>
                    setQuantities((qs) =>
                      qs.map((q, i) =>
                        i === idx ? Math.max(1, Number(e.target.value) || 1) : q,
                      ),
                    )
                  }
                />
                <span className="text-xs text-zinc-500">g</span>
                <Button variant="outline" size="sm" onClick={() => step(idx, 10)} aria-label="Increase 10g">
                  <Plus className="h-3 w-3" />
                </Button>
              </div>
            </div>
            {item.reasoning && <p className="mt-2 text-xs italic text-zinc-600">{item.reasoning}</p>}
          </div>
        );
      })}

      <div className="flex items-center justify-between border-t border-zinc-800 pt-3">
        <p className="text-sm font-semibold">
          Total: {Math.round(totals.calories)} kcal · {Math.round(totals.protein_g)}g protein
        </p>
        <Button onClick={() => void confirm()} disabled={saving}>
          <Check className="h-4 w-4" />
          {saving ? "Saving…" : "Confirm & Add"}
        </Button>
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}
