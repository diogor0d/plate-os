/**
 * Manual quick-log ("Quick Log" from the brief's bottom nav): a compact form
 * for per-100g values + quantity that funnels through the same Proposal Card
 * confirmation flow as every other input path. Works fully offline (the card
 * enqueues to Dexie when the POST fails).
 */
import { useState } from "react";
import { Button } from "./ui/button";
import { ProposalCard, type ProposalCardItem } from "./ProposalCard";

export function ManualEntry({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [quantity, setQuantity] = useState("100");
  const [calories, setCalories] = useState("");
  const [protein, setProtein] = useState("");
  const [carbs, setCarbs] = useState("");
  const [fat, setFat] = useState("");
  const [fiber, setFiber] = useState("0");
  const [proposal, setProposal] = useState<ProposalCardItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const parseNumber = (value: string) => Number(value.trim().replace(",", "."));
    const values = {
      calories: parseNumber(calories),
      protein_g: parseNumber(protein || "0"),
      carbs_g: parseNumber(carbs || "0"),
      fat_g: parseNumber(fat || "0"),
      fiber_g: parseNumber(fiber || "0"),
      quantity: parseNumber(quantity),
    };
    if (!name.trim() || !calories) return;
    if (
      !Object.values(values).every(Number.isFinite) ||
      values.calories < 0 ||
      values.calories > 1000 ||
      [values.protein_g, values.carbs_g, values.fat_g, values.fiber_g].some(
        (value) => value < 0 || value > 100,
      ) ||
      values.quantity < 0.01 ||
      values.quantity > 10000 ||
      Math.abs(Math.round(values.quantity * 100) - values.quantity * 100) > 1e-8
    ) {
      setError("Check the values: quantity supports 0.01-10,000 g and nutrients must be valid per-100 values.");
      return;
    }
    setError(null);
    setProposal([
      {
        name: name.trim(),
        per100: {
          calories: values.calories,
          protein_g: values.protein_g,
          carbs_g: values.carbs_g,
          fat_g: values.fat_g,
          fiber_g: values.fiber_g,
        },
        quantityG: values.quantity,
        sourceType: "manual",
      },
    ]);
  };

  if (proposal) {
    return <ProposalCard items={proposal} onDone={onDone} />;
  }

  const field =
    "w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-600 focus:outline-none";

  const nutrientField = (
    label: string,
    value: string,
    onChange: (value: string) => void,
    unit: string,
    required = false,
  ) => (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-zinc-300">
        {label}{required && <span className="ml-1 text-emerald-400">required</span>}
      </span>
      <div className="relative">
        <input
          className={`${field} pr-12 tabular-nums`}
          inputMode="decimal"
          aria-label={`${label} per 100 grams or milliliters`}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-zinc-600">{unit}</span>
      </div>
    </label>
  );

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Quick log</h2>
          <p className="mt-1 text-xs text-zinc-500">Enter the nutrition label, then tell us how much you consumed.</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onDone}>
          Close
        </Button>
      </div>

      <label className="block space-y-1.5">
        <span className="text-xs font-medium text-zinc-300">Food name <span className="ml-1 text-emerald-400">required</span></span>
        <input
          className={field}
          placeholder="e.g. Greek yogurt"
          maxLength={255}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </label>

      <fieldset className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-950/40 p-4">
        <legend className="px-1 text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-500">Nutrition per 100 g/ml</legend>
        <p className="text-xs text-zinc-600">Copy these values directly from the product label.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          {nutrientField("Calories", calories, setCalories, "kcal", true)}
          {nutrientField("Protein", protein, setProtein, "g")}
          {nutrientField("Carbohydrates", carbs, setCarbs, "g")}
          {nutrientField("Fat", fat, setFat, "g")}
          {nutrientField("Fiber", fiber, setFiber, "g")}
        </div>
      </fieldset>

      <div className="grid items-end gap-3 border-t border-zinc-800 pt-4 sm:grid-cols-[1fr_auto]">
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-zinc-300">Amount consumed <span className="ml-1 text-emerald-400">required</span></span>
          <div className="relative">
            <input
              className={`${field} pr-10 tabular-nums`}
              inputMode="decimal"
              aria-label="Amount consumed in grams or milliliters"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
            />
            <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-zinc-600">g/ml</span>
          </div>
        </label>
        <Button className="sm:min-w-32" onClick={submit} disabled={!name.trim() || !calories}>
          Review totals
        </Button>
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}
