import type { Per100, SourceType } from "./types";
import type { AnalyticsMetric } from "./analytics";

export type AssistantMode = "coach" | "goals" | "analytics";

export interface AnalyticsIntent {
  id: string;
  days?: number;
  start?: string;
  end?: string;
  metric: AnalyticsMetric;
  sourceTypes: SourceType[];
  foodQuery?: string;
}

export interface AssistantLaunch {
  id: string;
  prompt: string;
  mode: AssistantMode;
  surface: "today" | "coach" | "stats";
  analytics?: Omit<AnalyticsIntent, "id">;
}

export interface AssistantMealItem {
  name: string;
  estimated_weight_g: number;
  confidence: "high" | "medium" | "low";
  reasoning: string;
  per100: Per100;
}

export interface GoalTargets {
  target_calories: number;
  target_protein_g: number;
  target_carbs_g: number;
  target_fat_g: number;
}

export type AssistantBlock =
  | { type: "meal_proposal"; title: string; items: AssistantMealItem[] }
  | { type: "goal_draft"; proposed_targets: GoalTargets; rationale: string; caveats: string[] }
  | { type: "analytics_navigation"; label: string; description: string; query: Omit<AnalyticsIntent, "id"> }
  | { type: "evidence_insight"; title: string; interpretation: string; tone: "neutral" | "positive" | "warning" };

const sources: SourceType[] = ["vision_label", "text_estimate", "manual", "barcode"];
const metrics: AnalyticsMetric[] = ["calories", "protein_g", "carbs_g", "fat_g", "fiber_g"];
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;
const finite = (value: unknown, min: number, max: number): value is number => typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
const text = (value: unknown, max: number): value is string => typeof value === "string" && value.length > 0 && value.length <= max;
const isoDate = (value: unknown): value is string => {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
};

function parsePer100(value: unknown): Per100 | null {
  if (!object(value)) return null;
  if (!finite(value.calories, 0, 1000) || !finite(value.protein_g, 0, 100) ||
      !finite(value.carbs_g, 0, 100) || !finite(value.fat_g, 0, 100) ||
      !finite(value.fiber_g, 0, 100)) return null;
  return { calories: value.calories, protein_g: value.protein_g, carbs_g: value.carbs_g, fat_g: value.fat_g, fiber_g: value.fiber_g };
}

function parseAnalyticsQuery(value: unknown): Omit<AnalyticsIntent, "id"> | null {
  if (!object(value) || !metrics.includes(value.metric as AnalyticsMetric)) return null;
  const sourceTypes = Array.isArray(value.source_types) ? value.source_types : [];
  if (sourceTypes.length > 4 || new Set(sourceTypes).size !== sourceTypes.length || !sourceTypes.every((source) => sources.includes(source as SourceType))) return null;
  const days = value.days;
  const start = value.start;
  const end = value.end;
  if (days !== undefined && days !== null && (!finite(days, 1, 366) || !Number.isInteger(days))) return null;
  if (days != null && start != null) return null;
  if ((start == null) !== (end == null)) return null;
  if (start != null) {
    if (!isoDate(start) || !isoDate(end)) return null;
    const startTime = Date.parse(`${start}T00:00:00Z`);
    const endTime = Date.parse(`${end}T00:00:00Z`);
    if (!Number.isFinite(startTime) || !Number.isFinite(endTime) || startTime > endTime || (endTime - startTime) / 86_400_000 + 1 > 366) return null;
  }
  if (days == null && start == null) return null;
  if (value.food_query != null && !text(value.food_query, 100)) return null;
  return {
    days: typeof days === "number" ? days : undefined,
    start: typeof start === "string" ? start : undefined,
    end: typeof end === "string" ? end : undefined,
    metric: value.metric as AnalyticsMetric,
    sourceTypes: sourceTypes as SourceType[],
    foodQuery: typeof value.food_query === "string" ? value.food_query : undefined,
  };
}

export function parseAssistantBlock(value: unknown): AssistantBlock | null {
  if (!object(value) || typeof value.type !== "string") return null;
  if (value.type === "meal_proposal") {
    if (!text(value.title, 100) || !Array.isArray(value.items) || value.items.length < 1 || value.items.length > 8) return null;
    const items: AssistantMealItem[] = [];
    for (const item of value.items) {
      if (!object(item) || !text(item.name, 255) || !finite(item.estimated_weight_g, 0.01, 10000) ||
          !["high", "medium", "low"].includes(String(item.confidence)) || !text(item.reasoning, 500)) return null;
      const per100 = parsePer100(item.per100);
      if (!per100) return null;
      items.push({ name: item.name, estimated_weight_g: item.estimated_weight_g, confidence: item.confidence as AssistantMealItem["confidence"], reasoning: item.reasoning, per100 });
    }
    return { type: "meal_proposal", title: value.title, items };
  }
  if (value.type === "goal_draft") {
    if (!object(value.proposed_targets) || !text(value.rationale, 800)) return null;
    const targets = value.proposed_targets;
    if (!finite(targets.target_calories, 800, 6000) || !finite(targets.target_protein_g, 20, 400) ||
        !finite(targets.target_carbs_g, 0, 800) || !finite(targets.target_fat_g, 20, 300) ||
        !Number.isInteger(targets.target_calories) || !Number.isInteger(targets.target_protein_g) ||
        !Number.isInteger(targets.target_carbs_g) || !Number.isInteger(targets.target_fat_g)) return null;
    if (!Array.isArray(value.caveats) || value.caveats.length > 5 || !value.caveats.every((item) => text(item, 300))) return null;
    const caveats = value.caveats as string[];
    return { type: "goal_draft", proposed_targets: targets as unknown as GoalTargets, rationale: value.rationale, caveats };
  }
  if (value.type === "analytics_navigation") {
    const query = parseAnalyticsQuery(value.query);
    if (!query || !text(value.label, 80) || !text(value.description, 240)) return null;
    return { type: "analytics_navigation", label: value.label, description: value.description, query };
  }
  if (value.type === "evidence_insight") {
    if (!text(value.title, 100) || !text(value.interpretation, 600) || !["neutral", "positive", "warning"].includes(String(value.tone))) return null;
    return { type: "evidence_insight", title: value.title, interpretation: value.interpretation, tone: value.tone as "neutral" | "positive" | "warning" };
  }
  return null;
}
