import { describe, expect, it } from "vitest";
import { buildAnalyticsQuery, macroEnergyShare, rollingAverage, weekdayAverages } from "./analytics";
import type { DayTotals } from "./types";

const day = (date: string, overrides: Partial<DayTotals> = {}): DayTotals => ({
  date,
  meal_count: 1,
  calories: 100,
  protein_g: 10,
  carbs_g: 10,
  fat_g: 10,
  fiber_g: 2,
  ...overrides,
});

describe("analytics helpers", () => {
  it("serializes stable preset and source filters", () => {
    expect(buildAnalyticsQuery({ days: 30, sourceTypes: ["manual", "barcode"], foodQuery: "oats & milk" }))
      .toBe("days=30&source_type=barcode&source_type=manual&q=oats+%26+milk");
  });

  it("uses custom dates instead of days", () => {
    expect(buildAnalyticsQuery({ start: "2026-08-01", end: "2026-08-31", sourceTypes: [] }))
      .toBe("start=2026-08-01&end=2026-08-31");
  });

  it("does not emit a rolling value before a full window", () => {
    expect(rollingAverage([1, 2, 3], 3)).toEqual([null, null, 2]);
  });

  it("calculates macro energy percentages", () => {
    const result = macroEnergyShare([day("2026-08-31", { protein_g: 25, carbs_g: 25, fat_g: 0 })]);
    expect(result.map((item) => item.percent)).toEqual([50, 50, 0]);
  });

  it("groups local date strings without browser-timezone drift", () => {
    const result = weekdayAverages([
      day("2026-08-30", { calories: 100 }),
      day("2026-08-31", { calories: 300 }),
    ], "calories");
    expect(result.find((item) => item.day === "Sun")?.value).toBe(100);
    expect(result.find((item) => item.day === "Mon")?.value).toBe(300);
  });
});
