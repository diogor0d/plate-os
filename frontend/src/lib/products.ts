import { api } from "./api";
import { canonicalizePer100 } from "./nutrition";
import type { Per100, SourceType } from "./types";

export type GenericFoodSource = "ciqual" | "swedish_food_agency";
export type ProductSource = "manual" | "open_food_facts" | "vision_label" | GenericFoodSource;

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
  nutrition_source_id: string | null;
  nutrition_source_version: string | null;
  accepted_at: string;
  updated_at: string;
  version: number;
  archived_at: string | null;
}

export interface ProductCandidate {
  source: Exclude<ProductSource, "manual">;
  source_id: string | null;
  source_version: string | null;
  barcode: string | null;
  name: string;
  brand: string | null;
  serving_unit: string;
  per100: Per100;
  suggested_quantity_g: number | null;
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
  nutritionSourceId: string | null;
  nutritionSourceVersion: string | null;
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
  nutrition_source_id: string | null;
  nutrition_source_version: string | null;
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
    nutritionSourceId: candidate.source_id,
    nutritionSourceVersion: candidate.source_version,
    acceptanceProof: candidate.acceptance_proof,
    candidateFingerprint: null,
  };
  draft.candidateFingerprint = boundDraftFingerprint(draft);
  return draft;
}

export function draftWithBoundCandidateBarcode(
  draft: ProductDraft,
  candidate: ProductCandidate,
): ProductDraft {
  const boundDraft = draftFromCandidate(candidate);
  return {
    ...draft,
    barcode: candidate.barcode ?? "",
    acceptanceProof: candidate.acceptance_proof,
    candidateFingerprint: boundDraft.candidateFingerprint,
  };
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
    nutritionSourceId: product.nutrition_source_id,
    nutritionSourceVersion: product.nutrition_source_version,
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
    nutritionSourceId: null,
    nutritionSourceVersion: null,
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
      nutrition_source_id: externalProofIsValid ? draft.nutritionSourceId : null,
      nutrition_source_version: externalProofIsValid ? draft.nutritionSourceVersion : null,
      acceptance_proof: externalProofIsValid ? draft.acceptanceProof : null,
    },
  };
}

function boundDraftFingerprint(draft: ProductDraft): string {
  return JSON.stringify({
    source: draft.nutritionSource,
    source_id: draft.nutritionSourceId,
    source_version: draft.nutritionSourceVersion,
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

export function bindCandidateBarcode(
  candidate: ProductCandidate,
  barcode: string,
): Promise<ProductCandidate> {
  return api<ProductCandidate>("/api/food-items/candidates/bind-barcode", {
    method: "POST",
    body: JSON.stringify({ candidate, barcode }),
  });
}

export function stableMutation(
  current: StableMutation | null,
  fingerprint: string,
  createId: () => string = () => crypto.randomUUID(),
): StableMutation {
  return current?.fingerprint === fingerprint ? current : { fingerprint, id: createId() };
}

export function sourceLabel(source: ProductSource, version?: string | null): string {
  return source === "manual"
    ? "Entered manually"
    : `${candidateSourceLabel(source, version)}, reviewed by you`;
}

export function candidateSourceLabel(
  source: Exclude<ProductSource, "manual">,
  version?: string | null,
): string {
  if (source === "open_food_facts") return "Open Food Facts candidate";
  if (source === "vision_label") return "Vision label extraction";
  if (source === "ciqual") return `Anses Ciqual ${version ?? "2025-11-19"} (Licence Ouverte 2.0)`;
  return `Swedish Food Agency ${version ?? "2026-07-01"} (CC BY 4.0)`;
}

export function productSourceToMealSource(source: ProductSource): SourceType {
  if (source === "open_food_facts") return "barcode";
  if (source === "vision_label") return "vision_label";
  return "manual";
}

export const productFingerprint = (value: object): string => JSON.stringify(value);

export async function listProducts(query = ""): Promise<Product[]> {
  const params = new URLSearchParams({ q: query, limit: "50" });
  return api<Product[]>(`/api/food-items?${params.toString()}`);
}

export async function searchProductCandidates(
  query: string,
  source: GenericFoodSource,
  limit = 10,
): Promise<ProductCandidate[]> {
  const params = new URLSearchParams({ q: query, source, limit: String(limit) });
  return api<ProductCandidate[]>(`/api/food-items/candidates/search?${params.toString()}`);
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
