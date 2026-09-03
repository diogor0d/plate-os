import { describe, expect, it, vi } from "vitest";
import {
  draftFromCandidate,
  draftWithBoundCandidateBarcode,
  stableMutation,
  validateProductDraft,
  type ProductCandidate,
} from "./products";

const candidate: ProductCandidate = {
  source: "open_food_facts",
  barcode: "123",
  name: "Oats",
  brand: "Example",
  serving_unit: "g",
  per100: { calories: 379, protein_g: 13.2, carbs_g: 67.7, fat_g: 6.5, fiber_g: 10.1 },
  suggested_quantity_g: null,
  retrieved_at: "2026-09-02T12:00:00Z",
  confidence_score: null,
  issues: [],
  acceptance_proof: "proof",
};

describe("product drafts", () => {
  it("preserves candidate provenance and nutrition in an editable draft", () => {
    const draft = draftFromCandidate(candidate);
    expect(draft).toMatchObject({
      barcode: "123",
      name: "Oats",
      nutritionSource: "open_food_facts",
      calories: "379",
    });
    expect(validateProductDraft(draft).value).toMatchObject({
      nutrition_source: "open_food_facts",
      acceptance_proof: "proof",
    });
  });

  it("normalizes decimal commas and optional values to the create contract", () => {
    const result = validateProductDraft({
      ...draftFromCandidate(candidate),
      brand: "  ",
      calories: "379,12345",
    });
    expect(result).toEqual({
      value: {
        barcode: "123",
        name: "Oats",
        brand: null,
        serving_unit: "g",
        nutrition_source: "manual",
        acceptance_proof: null,
        per100: { calories: 379.1235, protein_g: 13.2, carbs_g: 67.7, fat_g: 6.5, fiber_g: 10.1 },
      },
    });
  });

  it("drops external provenance and proof when a candidate field is edited", () => {
    const result = validateProductDraft({ ...draftFromCandidate(candidate), name: "Edited oats" });
    expect(result.value).toMatchObject({
      name: "Edited oats",
      nutrition_source: "manual",
      acceptance_proof: null,
    });
  });

  it("binds a scanned barcode without changing label values or provenance", () => {
    const labelCandidate: ProductCandidate = {
      ...candidate,
      source: "vision_label",
      barcode: null,
      suggested_quantity_g: 125,
      acceptance_proof: "original-proof",
    };
    const draft = draftFromCandidate(labelCandidate);
    const rebound = {
      ...labelCandidate,
      barcode: "5601234567890",
      acceptance_proof: "rebound-proof",
    };

    const attached = draftWithBoundCandidateBarcode(draft, rebound);

    expect(attached).toMatchObject({
      barcode: "5601234567890",
      calories: "379",
      acceptanceProof: "rebound-proof",
    });
    expect(validateProductDraft(attached).value).toMatchObject({
      barcode: "5601234567890",
      nutrition_source: "vision_label",
      acceptance_proof: "rebound-proof",
    });
  });

  it("rejects values outside backend limits", () => {
    const result = validateProductDraft({ ...draftFromCandidate(candidate), protein: "100.1" });
    expect(result.error).toContain("0-100");
  });
});

describe("stableMutation", () => {
  it("reuses an id for an identical retry and rotates it when the payload changes", () => {
    const createId = vi.fn().mockReturnValueOnce("first").mockReturnValueOnce("second");
    const first = stableMutation(null, "payload-a", createId);
    expect(stableMutation(first, "payload-a", createId)).toBe(first);
    expect(stableMutation(first, "payload-b", createId).id).toBe("second");
    expect(createId).toHaveBeenCalledTimes(2);
  });
});
