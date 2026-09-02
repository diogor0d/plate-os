import { describe, expect, it, vi } from "vitest";
import {
  buildAgendaQuery,
  buildRoutineWrite,
  countdownAt,
  formatCountdown,
  routineToProposalItems,
  stableRoutineMutation,
  timeResolutionMessage,
  validateRoutineDraft,
  validateSchedule,
  fetchAgenda,
  type Agenda,
  type Routine,
  type RoutineDraft,
} from "./routines";
import { api } from "./api";

const product = {
  id: "product-1",
  barcode: "123",
  name: "Oats",
  brand: "Plate",
  serving_unit: "g",
  calories_per_100: 370,
  protein_per_100: 13,
  carbs_per_100: 60,
  fat_per_100: 7,
  fiber_per_100: 10,
  nutrition_source: "open_food_facts" as const,
  accepted_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
  version: 1,
  archived_at: null,
};

const definedDraft: RoutineDraft = {
  title: "Breakfast",
  mode: "defined",
  roughText: "",
  items: [{ product, quantityG: 80 }],
};

describe("routine helpers", () => {
  it("refreshes agenda materialization with POST rather than GET", async () => {
    vi.mocked(api).mockResolvedValueOnce({} as Agenda);
    await fetchAgenda({ days: 14 });
    expect(api).toHaveBeenCalledWith("/api/agenda/refresh?days=14", { method: "POST" });
  });
  it("builds mode-exclusive routine writes with optimistic versions", () => {
    expect(buildRoutineWrite(definedDraft, "mutation-1", 3)).toEqual({
      client_mutation_id: "mutation-1",
      title: "Breakfast",
      mode: "defined",
      rough_text: null,
      items: [{ food_item_id: "product-1", quantity_g: 80 }],
      expected_version: 3,
    });
  });

  it("rejects duplicate products and invalid quantities", () => {
    expect(validateRoutineDraft({
      ...definedDraft,
      items: [{ product, quantityG: 80 }, { product, quantityG: 90 }],
    })).toContain("only once");
    expect(validateRoutineDraft({ ...definedDraft, items: [{ product, quantityG: 0 }] }))
      .toContain("Quantities");
  });

  it("validates recurrence-specific schedule fields", () => {
    const base = {
      local_time: "08:30",
      timezone: "Europe/Lisbon",
      frequency: "weekly" as const,
      interval: 2,
      iso_weekdays: [1, 5],
      start_date: "2026-09-02",
      end_date: null,
      reminder_minutes: 30,
    };
    expect(validateSchedule(base)).toBeNull();
    expect(validateSchedule({ ...base, iso_weekdays: [] })).toContain("weekday");
    expect(validateSchedule({ ...base, timezone: "Not/A_Zone" })).toContain("IANA");
    expect(validateSchedule({ ...base, end_date: "02/09/2026" })).toContain("valid end date");
  });

  it("serializes agenda ranges without mixing date and day modes", () => {
    expect(buildAgendaQuery({ days: 14 })).toBe("days=14");
    expect(buildAgendaQuery({ start: "2026-10-01", end: "2026-10-07", days: 30 }))
      .toBe("start=2026-10-01&end=2026-10-07");
  });

  it("uses the server countdown baseline", () => {
    const agenda: Agenda = {
      server_now: "2026-09-02T10:00:00Z",
      display_timezone: "Europe/Lisbon",
      occurrences: [],
      next_due_at: "2026-09-02T10:01:30Z",
      countdown_seconds: 90,
    };
    expect(countdownAt(agenda, 31.9)).toBe(59);
    expect(formatCountdown(countdownAt(agenda, 90))).toBe("Due now");
  });

  it("keeps an idempotency key for unchanged retries and rotates it after edits", () => {
    const first = stableRoutineMutation(null, "same", () => "first");
    expect(stableRoutineMutation(first, "same", () => "unused")).toBe(first);
    expect(stableRoutineMutation(first, "changed", () => "second").id).toBe("second");
  });

  it("explains DST resolution and converts only defined routines to proposals", () => {
    expect(timeResolutionMessage("ambiguous-earlier")).toContain("earlier occurrence");
    expect(timeResolutionMessage("nonexistent-shift-forward")).toContain("shifted it forward");
    const routine: Routine = {
      id: "routine-1",
      title: "Breakfast",
      mode: "defined",
      rough_text: null,
      version: 1,
      archived_at: null,
      created_at: "2026-09-01T00:00:00Z",
      updated_at: "2026-09-01T00:00:00Z",
      items: [{ position: 0, quantity_g: 80, product }],
    };
    expect(routineToProposalItems(routine)[0]).toMatchObject({
      foodItemId: "product-1",
      quantityG: 80,
      sourceType: "barcode",
    });
    expect(routineToProposalItems({ ...routine, mode: "rough", rough_text: "Something light" }))
      .toEqual([]);
  });
});

vi.mock("./api", () => ({ api: vi.fn() }));
