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

// Inputs have at most six relevant decimal places (density 4 x quantity 2).
// The small epsilon only corrects binary representation at exact half ties.
const round1 = (v: number) => Math.floor(v * 10 + 0.5 + 1e-9) / 10;

const round4 = (v: number) => Math.floor(v * 10_000 + 0.5 + 1e-9) / 10_000;

export function canonicalizePer100(per100: Per100): Per100 {
  return {
    calories: round4(per100.calories) || 0,
    protein_g: round4(per100.protein_g) || 0,
    carbs_g: round4(per100.carbs_g) || 0,
    fat_g: round4(per100.fat_g) || 0,
    fiber_g: round4(per100.fiber_g) || 0,
  };
}

export function scaleToQuantity(per100: Per100, quantityG: number): Totals {
  const canonical = canonicalizePer100(per100);
  return Object.fromEntries(
    MACRO_FIELDS.map((f) => [f, round1((canonical[f] * quantityG) / 100)]),
  ) as Totals;
}

export function sumTotals(items: Totals[]): Totals {
  return Object.fromEntries(
    MACRO_FIELDS.map((f) => [f, round1(items.reduce((acc, i) => acc + i[f], 0))]),
  ) as Totals;
}
