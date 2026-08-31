import { useDeferredValue, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
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
import {
  buildAnalyticsQuery,
  macroEnergyShare,
  rollingAverage,
  weekdayAverages,
  type AnalyticsMetric,
} from "../lib/analytics";
import { api } from "../lib/api";
import type { AnalyticsResponse, SourceType } from "../lib/types";
import { Card } from "./ui/card";

const EMERALD = "#10b981";
const GRID = "#27272a";
const SOURCE_OPTIONS: { id: SourceType; label: string }[] = [
  { id: "barcode", label: "Barcode" },
  { id: "vision_label", label: "Label photo" },
  { id: "text_estimate", label: "Coach" },
  { id: "manual", label: "Manual" },
];
const METRICS: Record<AnalyticsMetric, { label: string; unit: string; target?: keyof AnalyticsResponse["targets"] }> = {
  calories: { label: "Calories", unit: "kcal", target: "calories" },
  protein_g: { label: "Protein", unit: "g", target: "protein_g" },
  carbs_g: { label: "Carbohydrates", unit: "g", target: "carbs_g" },
  fat_g: { label: "Fat", unit: "g", target: "fat_g" },
  fiber_g: { label: "Fiber", unit: "g" },
};
const inputClass = "rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs text-zinc-200 focus:border-emerald-600 focus:outline-none";

function isoInputDate(date: Date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <Card className="space-y-1">
      <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-500">{label}</p>
      <p className="text-2xl font-semibold tracking-tight text-zinc-100">{value}</p>
      <p className="text-xs text-zinc-600">{detail}</p>
    </Card>
  );
}

export function Analytics() {
  const [days, setDays] = useState(30);
  const [customRange, setCustomRange] = useState(false);
  const [start, setStart] = useState(() => {
    const date = new Date();
    date.setDate(date.getDate() - 29);
    return isoInputDate(date);
  });
  const [end, setEnd] = useState(() => isoInputDate(new Date()));
  const [sources, setSources] = useState<SourceType[]>([]);
  const [foodQuery, setFoodQuery] = useState("");
  const [metric, setMetric] = useState<AnalyticsMetric>("calories");
  const deferredFoodQuery = useDeferredValue(foodQuery);
  const validRange = !customRange || (!!start && !!end && start <= end);
  const queryString = buildAnalyticsQuery({
    days: customRange ? undefined : days,
    start: customRange ? start : undefined,
    end: customRange ? end : undefined,
    sourceTypes: sources,
    foodQuery: deferredFoodQuery,
  });
  const analytics = useQuery({
    queryKey: ["analytics", queryString],
    queryFn: () => api<AnalyticsResponse>(`/api/analytics/daily?${queryString}`),
    enabled: validRange,
    placeholderData: (previous) => previous,
  });

  const data = analytics.data;
  const config = METRICS[metric];
  const rolling = rollingAverage(data?.history.map((day) => day[metric]) ?? []);
  const chartData = (data?.history ?? []).map((day, index) => ({
    ...day,
    label: day.date.slice(5),
    value: day[metric],
    rolling: rolling[index],
  }));
  const target = data && config.target ? data.targets[config.target] : undefined;
  const macros = macroEnergyShare(data?.history ?? []);
  const weekdays = weekdayAverages(data?.history ?? [], metric);

  const toggleSource = (source: SourceType) => {
    setSources((current) => current.includes(source)
      ? current.filter((item) => item !== source)
      : [...current, source]);
  };

  return (
    <div className="space-y-5">
      <Card className="space-y-4 bg-zinc-900/35">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <p className="mb-2 text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-500">Range</p>
            <div className="flex flex-wrap gap-1.5">
              {[7, 14, 30, 90].map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => { setDays(preset); setCustomRange(false); }}
                  className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                    !customRange && days === preset
                      ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300"
                      : "border-zinc-700 text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {preset} days
                </button>
              ))}
              <button
                type="button"
                onClick={() => setCustomRange(true)}
                className={`rounded-lg border px-3 py-1.5 text-xs ${customRange ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300" : "border-zinc-700 text-zinc-500 hover:text-zinc-300"}`}
              >
                Custom
              </button>
            </div>
          </div>
          {customRange && (
            <div className="flex items-center gap-2">
              <label className="space-y-1 text-[10px] uppercase tracking-wider text-zinc-500">
                <span className="block">From</span>
                <input type="date" className={inputClass} value={start} onChange={(event) => setStart(event.target.value)} />
              </label>
              <label className="space-y-1 text-[10px] uppercase tracking-wider text-zinc-500">
                <span className="block">To</span>
                <input type="date" className={inputClass} value={end} onChange={(event) => setEnd(event.target.value)} />
              </label>
            </div>
          )}
          <label className="ml-auto space-y-1 text-[10px] uppercase tracking-wider text-zinc-500">
            <span className="block">Graph metric</span>
            <select className={inputClass} value={metric} onChange={(event) => setMetric(event.target.value as AnalyticsMetric)}>
              {Object.entries(METRICS).map(([id, item]) => <option key={id} value={id}>{item.label}</option>)}
            </select>
          </label>
        </div>

        <div className="flex flex-wrap items-end gap-3 border-t border-zinc-800 pt-4">
          <div>
            <p className="mb-2 text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-500">Input source</p>
            <div className="flex flex-wrap gap-1.5">
              {SOURCE_OPTIONS.map((source) => (
                <button
                  key={source.id}
                  type="button"
                  onClick={() => toggleSource(source.id)}
                  className={`rounded-full border px-3 py-1 text-xs ${sources.includes(source.id) ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300" : "border-zinc-700 text-zinc-500 hover:text-zinc-300"}`}
                >
                  {source.label}
                </button>
              ))}
            </div>
          </div>
          <label className="min-w-52 flex-1 space-y-1 text-[10px] uppercase tracking-wider text-zinc-500 md:max-w-xs">
            <span className="block">Food contains</span>
            <input
              type="search"
              className={`${inputClass} w-full normal-case tracking-normal`}
              placeholder="e.g. oats"
              value={foodQuery}
              onChange={(event) => setFoodQuery(event.target.value)}
            />
          </label>
          {(sources.length > 0 || foodQuery) && (
            <button type="button" className="pb-2 text-xs text-zinc-500 hover:text-zinc-200" onClick={() => { setSources([]); setFoodQuery(""); }}>
              Clear filters
            </button>
          )}
        </div>
        {!validRange && <p className="text-xs text-red-400">The end date must be on or after the start date.</p>}
      </Card>

      {analytics.isLoading && <div className="h-64 animate-pulse rounded-xl bg-zinc-900" />}
      {analytics.error && <p className="rounded-xl border border-red-900/50 p-4 text-sm text-red-300">Statistics could not be loaded. Check the selected range and connection.</p>}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Daily energy" value={`${Math.round(data.summary.avg_calories_per_day)} kcal`} detail={`${Math.round(data.targets.calories)} kcal current target`} />
            <Stat label="Daily protein" value={`${Math.round(data.summary.avg_protein_g_per_day)} g`} detail={`${Math.round(data.targets.protein_g)} g current target`} />
            <Stat label="Logging coverage" value={`${data.summary.active_days} / ${data.summary.calendar_days}`} detail="active days in range" />
            <Stat label="Meals logged" value={String(data.summary.meal_count)} detail={`${data.summary.avg_meals_per_active_day} per active day`} />
          </div>

          <Card>
            <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
              <div>
                <p className="text-sm font-semibold text-zinc-200">{config.label} over time</p>
                <p className="text-xs text-zinc-600">Daily total and 7-day moving average · {data.start_date} to {data.end_date}</p>
              </div>
              <span className="text-xs text-zinc-500">{config.unit}</span>
            </div>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -14 }}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="label" tick={{ fill: "#71717a", fontSize: 10 }} tickLine={false} minTickGap={22} />
                  <YAxis tick={{ fill: "#71717a", fontSize: 10 }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }} labelFormatter={(_, payload) => payload?.[0]?.payload.date ?? ""} />
                  {target !== undefined && <ReferenceLine y={target} stroke="#f43f5e" strokeDasharray="4 4" label={{ value: "target", fill: "#f43f5e", fontSize: 10, position: "insideTopRight" }} />}
                  <Bar dataKey="value" name={config.label} fill="#3f3f46" radius={[3, 3, 0, 0]} />
                  <Line dataKey="rolling" name="7-day average" stroke={EMERALD} strokeWidth={2} dot={false} connectNulls={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <p className="text-sm font-semibold text-zinc-200">Macro energy share</p>
              <p className="mt-1 text-xs text-zinc-600">Calculated from protein, carbohydrates, and fat.</p>
              <div className="mt-3 flex items-center gap-5">
                <div className="h-44 w-44 shrink-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={macros.filter((item) => item.value > 0)} dataKey="value" nameKey="name" innerRadius={43} outerRadius={68} paddingAngle={3} strokeWidth={0}>
                        {macros.map((item) => <Cell key={item.name} fill={item.color} />)}
                      </Pie>
                      <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <ul className="flex-1 space-y-3">
                  {macros.map((item) => (
                    <li key={item.name} className="flex items-center gap-2 text-sm">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
                      <span className="text-zinc-400">{item.name}</span>
                      <span className="ml-auto font-medium text-zinc-200">{item.percent}%</span>
                    </li>
                  ))}
                </ul>
              </div>
            </Card>

            <Card>
              <p className="text-sm font-semibold text-zinc-200">Weekday pattern</p>
              <p className="mt-1 text-xs text-zinc-600">Average {config.label.toLowerCase()} by weekday.</p>
              <div className="mt-4 h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={weekdays} margin={{ top: 8, right: 4, bottom: 0, left: -18 }}>
                    <CartesianGrid stroke={GRID} vertical={false} />
                    <XAxis dataKey="day" tick={{ fill: "#71717a", fontSize: 10 }} tickLine={false} />
                    <YAxis tick={{ fill: "#71717a", fontSize: 10 }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }} />
                    <Bar dataKey="value" fill={EMERALD} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
            <Card>
              <p className="text-sm font-semibold text-zinc-200">Logging sources</p>
              <div className="mt-4 space-y-3">
                {data.source_breakdown.length === 0 && <p className="text-xs text-zinc-600">No entries in this range.</p>}
                {data.source_breakdown.map((source) => {
                  const option = SOURCE_OPTIONS.find((item) => item.id === source.source_type);
                  const percent = data.summary.meal_count ? Math.round((source.meal_count / data.summary.meal_count) * 100) : 0;
                  return (
                    <div key={source.source_type}>
                      <div className="mb-1 flex justify-between text-xs">
                        <span className="text-zinc-400">{option?.label ?? source.source_type}</span>
                        <span className="text-zinc-600">{source.meal_count} · {percent}%</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-zinc-800"><div className="h-full rounded-full bg-emerald-500/70" style={{ width: `${percent}%` }} /></div>
                    </div>
                  );
                })}
              </div>
            </Card>

            <Card className="overflow-hidden p-0">
              <div className="border-b border-zinc-800 px-4 py-4">
                <p className="text-sm font-semibold text-zinc-200">Top foods</p>
                <p className="mt-1 text-xs text-zinc-600">Ranked by total calories in the selected range.</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] text-left text-xs">
                  <thead className="text-[10px] uppercase tracking-wider text-zinc-600">
                    <tr><th className="px-4 py-2 font-medium">Food</th><th className="px-3 py-2 font-medium">Entries</th><th className="px-3 py-2 font-medium">Quantity</th><th className="px-3 py-2 font-medium">Calories</th><th className="px-4 py-2 font-medium">Protein</th></tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800">
                    {data.top_foods.map((food) => (
                      <tr key={food.name} className="text-zinc-400 hover:bg-zinc-800/30">
                        <td className="px-4 py-2.5 font-medium text-zinc-200"><button type="button" className="hover:text-emerald-300" onClick={() => setFoodQuery(food.name)}>{food.name}</button></td>
                        <td className="px-3 py-2.5">{food.meal_count}</td>
                        <td className="px-3 py-2.5">{Math.round(food.quantity_g)} g</td>
                        <td className="px-3 py-2.5">{Math.round(food.calories)} kcal</td>
                        <td className="px-4 py-2.5">{Math.round(food.protein_g)} g</td>
                      </tr>
                    ))}
                    {data.top_foods.length === 0 && <tr><td colSpan={5} className="px-4 py-6 text-center text-zinc-600">No foods match these filters.</td></tr>}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
