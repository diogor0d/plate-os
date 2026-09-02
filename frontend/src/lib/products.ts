import { api } from "./api";
import { canonicalizePer100 } from "./nutrition";
import type { Per100 } from "./types";

export type ProductSource = "manual" | "open_food_facts" | "vision_label";

export interface Product {
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
  nutrition_source: ProductSource;
  accepted_at: string;
  updated_at: string;
  version: number;
  archived_at: string | null;
}

export interface ProductCandidate {
  source: "open_food_facts" | "vision_label";
  barcode: string | null;
  name: string;
  brand: string | null;
  serving_unit: string;
  per100: Per100;
  retrieved_at: string;
  confidence_score: number | null;
  issues: CandidateIssue[];
  acceptance_proof: string;
}

export type CandidateIssue =
  | "missing_name"
  | "missing_calories"
  | "missing_protein"
  | "missing_carbs"
  | "missing_fat"
  | "missing_fiber";

export type BarcodeResolution =
  | { kind: "accepted"; product: Product }
  | { kind: "candidate"; candidate: ProductCandidate }
  | { kind: "not_found"; barcode: string };

export interface ProductDraft {
  barcode: string;
  name: string;
  brand: string;
  servingUnit: string;
  calories: string;
  protein: string;
  carbs: string;
  fat: string;
  fiber: string;
  nutritionSource: ProductSource;
  acceptanceProof: string | null;
  candidateFingerprint: string | null;
}

export interface ValidProductDraft {
  barcode: string | null;
  name: string;
  brand: string | null;
  serving_unit: string;
  per100: Per100;
  nutrition_source: ProductSource;
  acceptance_proof: string | null;
}

export interface StableMutation {
  fingerprint: string;
  id: string;
}

const numberValue = (value: string) => Number(value.trim().replace(",", "."));

export function per100FromProduct(product: Product): Per100 {
  return {
    calories: product.calories_per_100,
    protein_g: product.protein_per_100,
    carbs_g: product.carbs_per_100,
    fat_g: product.fat_per_100,
    fiber_g: product.fiber_per_100,
  };
}

export function draftFromCandidate(candidate: ProductCandidate): ProductDraft {
  const draft: ProductDraft = {
    barcode: candidate.barcode ?? "",
    name: candidate.name,
    brand: candidate.brand ?? "",
    servingUnit: candidate.serving_unit,
    calories: String(candidate.per100.calories),
    protein: String(candidate.per100.protein_g),
    carbs: String(candidate.per100.carbs_g),
    fat: String(candidate.per100.fat_g),
    fiber: String(candidate.per100.fiber_g),
    nutritionSource: candidate.source,
    acceptanceProof: candidate.acceptance_proof,
    candidateFingerprint: null,
  };
  draft.candidateFingerprint = boundDraftFingerprint(draft);
  return draft;
}

export function draftFromProduct(product: Product): ProductDraft {
  const per100 = per100FromProduct(product);
  return {
    barcode: product.barcode ?? "",
    name: product.name,
    brand: product.brand ?? "",
    servingUnit: product.serving_unit,
    calories: String(per100.calories),
    protein: String(per100.protein_g),
    carbs: String(per100.carbs_g),
    fat: String(per100.fat_g),
    fiber: String(per100.fiber_g),
    nutritionSource: product.nutrition_source,
    acceptanceProof: null,
    candidateFingerprint: null,
  };
}

export function emptyProductDraft(): ProductDraft {
  return {
    barcode: "",
    name: "",
    brand: "",
    servingUnit: "g",
    calories: "",
    protein: "0",
    carbs: "0",
    fat: "0",
    fiber: "0",
    nutritionSource: "manual",
    acceptanceProof: null,
    candidateFingerprint: null,
  };
}

export function validateProductDraft(draft: ProductDraft):
  | { value: ValidProductDraft; error?: never }
  | { value?: never; error: string } {
  const per100 = {
    calories: numberValue(draft.calories),
    protein_g: numberValue(draft.protein),
    carbs_g: numberValue(draft.carbs),
    fat_g: numberValue(draft.fat),
    fiber_g: numberValue(draft.fiber),
  };
  if (!draft.name.trim() || draft.name.trim().length > 255) {
    return { error: "Name is required and must be 255 characters or fewer." };
  }
  if (!draft.servingUnit.trim() || draft.servingUnit.trim().length > 32) {
    return { error: "Serving unit is required and must be 32 characters or fewer." };
  }
  if (draft.barcode.trim().length > 64 || draft.brand.trim().length > 255) {
    return { error: "Barcode must be at most 64 characters and brand at most 255." };
  }
  if (
    !Object.values(per100).every(Number.isFinite) ||
    per100.calories < 0 ||
    per100.calories > 1000 ||
    [per100.protein_g, per100.carbs_g, per100.fat_g, per100.fiber_g].some(
      (value) => value < 0 || value > 100,
    )
  ) {
    return { error: "Use 0-1,000 kcal and 0-100 g for each nutrient per 100 g/ml." };
  }
  const externalProofIsValid = candidateDraftIsUnchanged(draft);
  return {
    value: {
      barcode: draft.barcode.trim() || null,
      name: draft.name.trim(),
      brand: draft.brand.trim() || null,
      serving_unit: draft.servingUnit.trim(),
      per100: canonicalizePer100(per100),
      nutrition_source: externalProofIsValid ? draft.nutritionSource : "manual",
      acceptance_proof: externalProofIsValid ? draft.acceptanceProof : null,
    },
  };
}

function boundDraftFingerprint(draft: ProductDraft): string {
  return JSON.stringify({
    source: draft.nutritionSource,
    barcode: draft.barcode.trim() || null,
    name: draft.name.trim(),
    brand: draft.brand.trim() || null,
    serving_unit: draft.servingUnit.trim(),
    per100: canonicalizePer100({
      calories: numberValue(draft.calories),
      protein_g: numberValue(draft.protein),
      carbs_g: numberValue(draft.carbs),
      fat_g: numberValue(draft.fat),
      fiber_g: numberValue(draft.fiber),
    }),
  });
}

export function candidateDraftIsUnchanged(draft: ProductDraft): boolean {
  return draft.nutritionSource !== "manual"
    && draft.acceptanceProof !== null
    && draft.candidateFingerprint === boundDraftFingerprint(draft);
}

export function stableMutation(
  current: StableMutation | null,
  fingerprint: string,
  createId: () => string = () => crypto.randomUUID(),
): StableMutation {
  return current?.fingerprint === fingerprint ? current : { fingerprint, id: createId() };
}

export function sourceLabel(source: ProductSource): string {
  if (source === "open_food_facts") return "Open Food Facts, reviewed by you";
  if (source === "vision_label") return "Label photo, reviewed by you";
  return "Entered manually";
}

export const productFingerprint = (value: object): string => JSON.stringify(value);

export async function listProducts(query = ""): Promise<Product[]> {
  const params = new URLSearchParams({ q: query, limit: "50" });
  return api<Product[]>(`/api/food-items?${params.toString()}`);
}

export async function createProduct(value: ValidProductDraft, mutationId: string): Promise<Product> {
  return api<Product>("/api/food-items", {
    method: "POST",
    body: JSON.stringify({ ...value, client_mutation_id: mutationId }),
  });
}

export async function updateProduct(
  product: Product,
  value: ValidProductDraft,
  mutationId: string,
): Promise<Product> {
  return api<Product>(`/api/food-items/${encodeURIComponent(product.id)}`, {
    method: "PATCH",
    body: JSON.stringify({
      client_mutation_id: mutationId,
      expected_version: product.version,
      name: value.name,
      brand: value.brand,
      serving_unit: value.serving_unit,
      per100: value.per100,
    }),
  });
}

export async function archiveProduct(product: Product, mutationId: string): Promise<Product> {
  return api<Product>(`/api/food-items/${encodeURIComponent(product.id)}/archive`, {
    method: "POST",
    body: JSON.stringify({ client_mutation_id: mutationId, expected_version: product.version }),
  });
}
