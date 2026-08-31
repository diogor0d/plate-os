import type { DayTotals, SourceType } from "./types";

export type AnalyticsMetric = "calories" | "protein_g" | "carbs_g" | "fat_g" | "fiber_g";

export function buildAnalyticsQuery(options: {
  days?: number;
  start?: string;
  end?: string;
  sourceTypes: SourceType[];
  foodQuery?: string;
}): string {
  const params = new URLSearchParams();
  if (options.start && options.end) {
    params.set("start", options.start);
    params.set("end", options.end);
  } else {
    params.set("days", String(options.days ?? 30));
  }
  for (const source of [...options.sourceTypes].sort()) params.append("source_type", source);
  if (options.foodQuery?.trim()) params.set("q", options.foodQuery.trim());
  return params.toString();
}

export function rollingAverage(values: number[], window = 7): (number | null)[] {
  return values.map((_, index) => {
    if (index < window - 1) return null;
    const slice = values.slice(index - window + 1, index + 1);
    return Math.round((slice.reduce((sum, value) => sum + value, 0) / window) * 10) / 10;
  });
}

export function macroEnergyShare(history: DayTotals[]) {
  const values = [
    { name: "Protein", value: history.reduce((sum, day) => sum + day.protein_g * 4, 0), color: "#10b981" },
    { name: "Carbs", value: history.reduce((sum, day) => sum + day.carbs_g * 4, 0), color: "#71717a" },
    { name: "Fat", value: history.reduce((sum, day) => sum + day.fat_g * 9, 0), color: "#a1a1aa" },
  ];
  const total = values.reduce((sum, item) => sum + item.value, 0);
  return values.map((item) => ({
    ...item,
    value: Math.round(item.value),
    percent: total > 0 ? Math.round((item.value / total) * 100) : 0,
  }));
}

export function weekdayAverages(history: DayTotals[], metric: AnalyticsMetric) {
  const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const buckets = weekdays.map((day) => ({ day, total: 0, count: 0 }));
  for (const item of history) {
    const weekday = new Date(`${item.date}T00:00:00Z`).getUTCDay();
    buckets[weekday].total += item[metric];
    buckets[weekday].count += 1;
  }
  return buckets.map(({ day, total, count }) => ({
    day,
    value: count ? Math.round((total / count) * 10) / 10 : 0,
  }));
}
