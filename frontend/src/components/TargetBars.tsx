import type { DailySummary } from "../lib/types";

function Bar({
  label,
  value,
  target,
  unit,
}: {
  label: string;
  value: number;
  target: number;
  unit: string;
}) {
  const pct = target > 0 ? Math.min(100, (value / target) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-zinc-400">
        <span>{label}</span>
        <span>
          {Math.round(value)} / {target}
          {unit}
        </span>
      </div>
      <div className="h-2 rounded-full bg-zinc-800">
        <div
          className="h-2 rounded-full bg-emerald-500 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function TargetBars({ summary }: { summary: DailySummary | undefined }) {
  if (!summary) return <div className="h-28 animate-pulse rounded-xl bg-zinc-900" />;
  return (
    <div className="space-y-3">
      <Bar label="Calories" value={summary.consumed.calories} target={summary.targets.calories} unit=" kcal" />
      <Bar label="Protein" value={summary.consumed.protein_g} target={summary.targets.protein_g} unit="g" />
      <Bar label="Carbs" value={summary.consumed.carbs_g} target={summary.targets.carbs_g} unit="g" />
      <Bar label="Fat" value={summary.consumed.fat_g} target={summary.targets.fat_g} unit="g" />
    </div>
  );
}
