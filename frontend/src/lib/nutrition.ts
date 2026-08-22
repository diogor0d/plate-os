/**
 * Client-side mirror of backend/app/services/nutrition.py (decision D13).
 * The same deterministic arithmetic runs on both sides so proposal-card
 * quantity edits recompute instantly without a round-trip. Keep the two
 * implementations in sync — same fields, same rounding.
 */
import type { Per100 } from "./types";

const MACRO_FIELDS = ["calories", "protein_g", "carbs_g", "fat_g", "fiber_g"] as const;

export type MacroField = (typeof MACRO_FIELDS)[number];
export type Totals = Record<MacroField, number>;

const round1 = (v: number) => Math.round(v * 10) / 10;

export function scaleToQuantity(per100: Per100, quantityG: number): Totals {
  return Object.fromEntries(
    MACRO_FIELDS.map((f) => [f, round1((per100[f] * quantityG) / 100)]),
  ) as Totals;
}

export function sumTotals(items: Totals[]): Totals {
  return Object.fromEntries(
    MACRO_FIELDS.map((f) => [f, round1(items.reduce((acc, i) => acc + i[f], 0))]),
  ) as Totals;
}
