/** TypeScript mirrors of the backend's API schemas (app/schemas/api.py). */

export interface Per100 {
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
}

export type SourceType = "vision_label" | "text_estimate" | "manual" | "barcode";

export interface DailySummary {
  date: string;
  timezone: string;
  targets: Record<string, number>;
  consumed: Record<string, number>;
  remaining: Record<string, number>;
}

export interface MealLog {
  id: string;
  logged_at: string;
  food_item_id: string | null;
  custom_name: string | null;
  quantity_g: number;
  calculated_calories: number;
  calculated_protein: number;
  calculated_carbs: number;
  calculated_fat: number;
  calculated_fiber: number;
  source_type: string;
}

export interface FoodItem {
  id: string;
  barcode: string | null;
  name: string;
  brand: string | null;
  serving_unit: string;
  calories_per_100: number;
  protein_per_100: number;
  carbs_per_100: number;
  fat_per_100: number;
  fiber_per_100: number;
  is_verified: boolean;
}

export interface MealLogCreate {
  logged_at?: string | null;
  food_item_id?: string | null;
  custom_name?: string | null;
  quantity_g: number;
  per100?: Per100 | null;
  source_type: SourceType;
}

/** Assistant tool-call item (backend contract: LogProposalResponse). */
export interface ProposalItem {
  name: string;
  estimated_weight_g: number;
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  confidence: "high" | "medium" | "low";
  reasoning: string;
  per100: Per100;
}

export interface DayTotals {
  date: string;
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
}

export interface AnalyticsResponse {
  timezone: string;
  days: number;
  targets: Record<string, number>;
  history: DayTotals[];
  rolling_avg_calories_7d: number;
}
