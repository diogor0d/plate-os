import { describe, expect, it } from "vitest";
import { dateRangeEndingOn, formatMealTime } from "./dates";

describe("account-local dates", () => {
  it("shows a meal in the account timezone across a date boundary", () => {
    const instant = "2026-07-01T00:30:00Z";
    expect(formatMealTime(instant, "Europe/Lisbon", "en-GB")).toBe("01:30");
    expect(formatMealTime(instant, "America/New_York", "en-GB")).toBe("20:30");
  });

  it("builds a calendar-day range across a daylight-saving change", () => {
    expect(dateRangeEndingOn("2026-04-02", 7)).toEqual({ start: "2026-03-27", end: "2026-04-02" });
  });
});
