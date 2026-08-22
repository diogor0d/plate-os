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

  const submit = () => {
    if (!name.trim() || !calories) return;
    setProposal([
      {
        name: name.trim(),
        per100: {
          calories: Number(calories) || 0,
          protein_g: Number(protein) || 0,
          carbs_g: Number(carbs) || 0,
          fat_g: Number(fat) || 0,
          fiber_g: Number(fiber) || 0,
        },
        quantityG: Number(quantity) || 100,
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
    </div>
  );
}
