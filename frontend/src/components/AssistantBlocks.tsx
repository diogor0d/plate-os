import { BarChart3, Lightbulb, Target, Utensils } from "lucide-react";
import { useState } from "react";
import type { AnalyticsIntent, AssistantBlock } from "../lib/assistant";
import { GoalChangeReview } from "./GoalChangeReview";
import { ProposalCard } from "./ProposalCard";
import { Button } from "./ui/button";

export function AssistantBlocks({
  blocks,
  onOpenAnalytics,
}: {
  blocks: AssistantBlock[];
  onOpenAnalytics: (intent: AnalyticsIntent) => void;
}) {
  const [openMeal, setOpenMeal] = useState<number | null>(null);
  const [openGoals, setOpenGoals] = useState<number | null>(null);

  return (
    <div className="space-y-3">
      {blocks.map((block, index) => {
        if (block.type === "meal_proposal") {
          if (openMeal === index) {
            return (
              <ProposalCard
                key={`meal-${index}`}
                items={block.items.map((item) => ({
                  name: item.name,
                  per100: item.per100,
                  quantityG: item.estimated_weight_g,
                  confidence: item.confidence,
                  reasoning: item.reasoning,
                  sourceType: "text_estimate",
                }))}
                onDone={() => setOpenMeal(null)}
              />
            );
          }
          return (
            <div key={`meal-${index}`} className="flex items-center justify-between gap-3 rounded-xl border border-emerald-900/60 bg-emerald-950/10 p-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="rounded-lg bg-emerald-500/10 p-2 text-emerald-400"><Utensils className="h-4 w-4" /></span>
                <div><p className="text-sm font-medium text-zinc-200">{block.title}</p><p className="text-xs text-zinc-500">{block.items.length} item{block.items.length === 1 ? "" : "s"} · quantities remain editable</p></div>
              </div>
              <Button variant="outline" size="sm" onClick={() => setOpenMeal(index)}>Review idea</Button>
            </div>
          );
        }
        if (block.type === "goal_draft") {
          if (openGoals === index) {
            return <GoalChangeReview key={`goals-${index}`} proposed={block.proposed_targets} rationale={block.rationale} caveats={block.caveats} onDone={() => setOpenGoals(null)} />;
          }
          return (
            <div key={`goals-${index}`} className="flex items-center justify-between gap-3 rounded-xl border border-amber-900/50 bg-amber-950/10 p-3">
              <div className="flex min-w-0 items-center gap-3"><span className="rounded-lg bg-amber-500/10 p-2 text-amber-400"><Target className="h-4 w-4" /></span><div><p className="text-sm font-medium text-zinc-200">Goal draft ready</p><p className="text-xs text-zinc-500">Compare with current targets before saving</p></div></div>
              <Button variant="outline" size="sm" onClick={() => setOpenGoals(index)}>Review goals</Button>
            </div>
          );
        }
        if (block.type === "analytics_navigation") {
          return (
            <div key={`analytics-${index}`} className="flex items-center justify-between gap-3 rounded-xl border border-zinc-800 bg-zinc-900/50 p-3">
              <div className="flex min-w-0 items-center gap-3"><span className="rounded-lg bg-zinc-800 p-2 text-emerald-400"><BarChart3 className="h-4 w-4" /></span><div><p className="text-sm font-medium text-zinc-200">{block.label}</p><p className="text-xs text-zinc-500">{block.description}</p></div></div>
              <Button variant="outline" size="sm" onClick={() => onOpenAnalytics({ id: crypto.randomUUID(), ...block.query })}>Open stats</Button>
            </div>
          );
        }
        const tones = {
          neutral: "border-zinc-800 bg-zinc-900/40 text-zinc-400",
          positive: "border-emerald-900/50 bg-emerald-950/10 text-emerald-300",
          warning: "border-amber-900/50 bg-amber-950/10 text-amber-300",
        };
        return (
          <div key={`insight-${index}`} className={`rounded-xl border p-3 ${tones[block.tone]}`}>
            <div className="flex gap-2"><Lightbulb className="mt-0.5 h-4 w-4 shrink-0" /><div><p className="text-sm font-medium">{block.title}</p><p className="mt-1 text-xs leading-relaxed text-zinc-400">{block.interpretation}</p></div></div>
          </div>
        );
      })}
    </div>
  );
}
