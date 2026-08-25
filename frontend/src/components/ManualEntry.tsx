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
    "w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm";

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Quick log</h2>
        <Button variant="ghost" size="sm" onClick={onDone}>
          Close
        </Button>
      </div>
      <p className="text-xs text-zinc-500">Values are per 100 g/ml as printed on the label.</p>
      <input
        className={field}
        placeholder="Food name"
        maxLength={255}
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <div className="grid grid-cols-3 gap-2">
        <input className={field} inputMode="decimal" placeholder="kcal*" value={calories} onChange={(e) => setCalories(e.target.value)} />
        <input className={field} inputMode="decimal" placeholder="P (g)" value={protein} onChange={(e) => setProtein(e.target.value)} />
        <input className={field} inputMode="decimal" placeholder="C (g)" value={carbs} onChange={(e) => setCarbs(e.target.value)} />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <input className={field} inputMode="decimal" placeholder="F (g)" value={fat} onChange={(e) => setFat(e.target.value)} />
        <input className={field} inputMode="decimal" placeholder="Fiber (g)" value={fiber} onChange={(e) => setFiber(e.target.value)} />
        <input className={field} inputMode="decimal" placeholder="Qty (g)*" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
      </div>
      <Button className="w-full" onClick={submit} disabled={!name.trim() || !calories}>
        Review
      </Button>
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}
