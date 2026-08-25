import { describe, expect, it } from "vitest";
import { scaleToQuantity } from "./nutrition";

const emptyMacros = { protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0 };

describe("nutrition rounding", () => {
  it.each([
    [209, 5, 10.5],
    [45, 5, 2.3],
    [1, 5, 0.1],
  ])("rounds %s kcal at %sg to %s with positive half-up", (calories, quantity, expected) => {
    expect(scaleToQuantity({ calories, ...emptyMacros }, quantity).calories).toBe(expected);
  });

  it("canonicalizes density to four decimals before scaling", () => {
    expect(
      scaleToQuantity({ calories: 1.234499, ...emptyMacros }, 10000).calories,
    ).toBe(123.5);
  });
});
