/**
 * Stats view (Phase 4): daily calories with target line + 7-day rolling
 * average, and average macro distribution (energy share) over the window.
 */
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../lib/api";
import type { AnalyticsResponse } from "../lib/types";
import { Card } from "./ui/card";

const ZINC_700 = "#3f3f46";
const EMERALD = "#10b981";

function rollingAvg(values: number[], window = 7): (number | null)[] {
  return values.map((_, i) => {
    if (i < window - 1) return null;
    const slice = values.slice(i - window + 1, i + 1);
    return Math.round(slice.reduce((a, b) => a + b, 0) / window);
  });
}

export function Analytics() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics"],
    queryFn: () => api<AnalyticsResponse>("/api/analytics/daily?days=14"),
  });

  if (isLoading) return <div className="h-64 animate-pulse rounded-xl bg-zinc-900" />;
  if (error || !data)
    return <p className="py-6 text-sm text-zinc-500">Analytics unavailable.</p>;

  const avgLine = rollingAvg(data.history.map((d) => d.calories));
  const chartData = data.history.map((d, i) => ({
    date: d.date.slice(5), // MM-DD
    calories: Math.round(d.calories),
    avg: avgLine[i],
  }));
  const avg = (f: keyof (typeof data.history)[number]) =>
    data.history.reduce((acc, d) => acc + Number(d[f]), 0) / data.history.length;
  const macroKcal = [
    { name: "Protein", value: Math.round(avg("protein_g") * 4), color: EMERALD },
    { name: "Carbs", value: Math.round(avg("carbs_g") * 4), color: ZINC_700 },
    { name: "Fat", value: Math.round(avg("fat_g") * 9), color: "#71717a" },
  ];

  return (
    <div className="space-y-4">
      <h2 className="text-base font-semibold">Stats — last {data.days} days</h2>

      <div className="grid grid-cols-2 gap-3">
        <Card>
          <p className="text-xs text-zinc-500">7-day avg calories</p>
          <p className="text-xl font-semibold">
            {Math.round(data.rolling_avg_calories_7d)}
            <span className="text-xs text-zinc-500"> / {data.targets.calories} target</span>
          </p>
        </Card>
        <Card>
          <p className="text-xs text-zinc-500">Avg protein</p>
          <p className="text-xl font-semibold">
            {Math.round(avg("protein_g"))}
            <span className="text-xs text-zinc-500"> / {data.targets.protein_g}g target</span>
          </p>
        </Card>
      </div>

      <Card>
        <p className="mb-2 text-xs text-zinc-400">Daily calories (kcal) vs target</p>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
              <CartesianGrid stroke="#27272a" vertical={false} />
              <XAxis dataKey="date" tick={{ fill: "#71717a", fontSize: 10 }} tickLine={false} />
              <YAxis tick={{ fill: "#71717a", fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "#a1a1aa" }}
              />
              <ReferenceLine
                y={data.targets.calories}
                stroke="#f43f5e"
                strokeDasharray="4 4"
                label={{ value: "target", fill: "#f43f5e", fontSize: 10, position: "insideTopRight" }}
              />
              <Bar dataKey="calories" fill={ZINC_700} radius={[3, 3, 0, 0]} />
              <Line dataKey="avg" stroke={EMERALD} strokeWidth={2} dot={false} name="7-day avg" connectNulls={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card>
        <p className="mb-2 text-xs text-zinc-400">Avg macro distribution (energy share)</p>
        <div className="flex items-center gap-4">
          <div className="h-40 w-40 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={macroKcal}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={38}
                  outerRadius={62}
                  paddingAngle={3}
                  strokeWidth={0}
                >
                  {macroKcal.map((m) => (
                    <Cell key={m.name} fill={m.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="space-y-2 text-sm">
            {macroKcal.map((m) => (
              <li key={m.name} className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: m.color }} />
                <span className="text-zinc-300">{m.name}</span>
                <span className="text-zinc-500">{m.value} kcal/day</span>
              </li>
            ))}
          </ul>
        </div>
      </Card>
    </div>
  );
}
