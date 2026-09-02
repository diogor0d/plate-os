import { describe, expect, it } from "vitest";
import { parseAssistantBlock } from "./assistant";

describe("assistant harness parser", () => {
  it("accepts a bounded meal proposal", () => {
    const block = parseAssistantBlock({
      type: "meal_proposal",
      title: "Dinner",
      items: [{
        name: "Chicken bowl",
        estimated_weight_g: 350,
        confidence: "medium",
        reasoning: "Cooked mixed meal",
        per100: { calories: 150, protein_g: 12, carbs_g: 18, fat_g: 3, fiber_g: 2 },
      }],
    });
    expect(block?.type).toBe("meal_proposal");
  });

  it("rejects unknown actions and impossible nutrition", () => {
    expect(parseAssistantBlock({ type: "fetch_url", url: "https://example.com" })).toBeNull();
    expect(parseAssistantBlock({
      type: "meal_proposal",
      title: "Bad",
      items: [{ name: "Bad", estimated_weight_g: 1, confidence: "high", reasoning: "x", per100: { calories: 2000, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0 } }],
    })).toBeNull();
  });

  it("accepts constrained analytics navigation", () => {
    const block = parseAssistantBlock({
      type: "analytics_navigation",
      label: "Audit estimates",
      description: "Show coach-estimated entries.",
      query: { days: 30, metric: "calories", source_types: ["text_estimate"] },
    });
    expect(block).toMatchObject({ type: "analytics_navigation", query: { days: 30, sourceTypes: ["text_estimate"] } });
  });

  it("rejects mixed, duplicate, or oversized analytics ranges", () => {
    const base = { type: "analytics_navigation", label: "Open", description: "Open stats." };
    expect(parseAssistantBlock({ ...base, query: { days: 30, start: "2026-08-01", end: "2026-08-31", metric: "calories" } })).toBeNull();
    expect(parseAssistantBlock({ ...base, query: { days: 30, metric: "calories", source_types: ["manual", "manual"] } })).toBeNull();
    expect(parseAssistantBlock({ ...base, query: { start: "2025-01-01", end: "2026-08-31", metric: "calories" } })).toBeNull();
  });

  it("rejects fractional days and invalid calendar dates", () => {
    const base = { type: "analytics_navigation", label: "Open", description: "Open stats." };
    expect(parseAssistantBlock({ ...base, query: { days: 30.5, metric: "calories" } })).toBeNull();
    expect(parseAssistantBlock({ ...base, query: { start: "2026-02-30", end: "2026-03-01", metric: "calories" } })).toBeNull();
  });

  it("rejects unsafe or fractional goal drafts", () => {
    const goal = (target_calories: number) => parseAssistantBlock({
      type: "goal_draft",
      proposed_targets: { target_calories, target_protein_g: 140, target_carbs_g: 250, target_fat_g: 70 },
      rationale: "Draft",
      caveats: [],
    });
    expect(goal(0)).toBeNull();
    expect(goal(2200.5)).toBeNull();
    expect(goal(2200)?.type).toBe("goal_draft");
  });

  it("rejects oversized goal caveats", () => {
    expect(parseAssistantBlock({
      type: "goal_draft",
      proposed_targets: { target_calories: 2200, target_protein_g: 140, target_carbs_g: 250, target_fat_g: 70 },
      rationale: "Draft",
      caveats: ["x".repeat(301)],
    })).toBeNull();
  });

  it("accepts a confirmed rough meal-plan draft with a bounded schedule", () => {
    expect(parseAssistantBlock({
      type: "meal_plan_draft",
      title: "Weekday lunch",
      rough_text: "A protein, whole grain, and two vegetables.",
      schedule: {
        local_time: "12:30",
        timezone: "Europe/Lisbon",
        frequency: "weekly",
        interval: 1,
        iso_weekdays: [1, 3, 5],
        start_date: "2026-09-07",
        end_date: null,
        reminder_minutes: 30,
      },
      requires_user_confirmation: true,
    })).toMatchObject({ type: "meal_plan_draft", schedule: { iso_weekdays: [1, 3, 5] } });
  });

  it("rejects unsafe meal-plan confirmation, recurrence, dates, and timezone", () => {
    const schedule = {
      local_time: "12:30",
      timezone: "Europe/Lisbon",
      frequency: "weekly",
      interval: 1,
      iso_weekdays: [1],
      start_date: "2026-09-07",
      end_date: null,
      reminder_minutes: null,
    };
    const draft = { type: "meal_plan_draft", title: "Lunch", rough_text: "A balanced lunch.", schedule, requires_user_confirmation: true };
    expect(parseAssistantBlock({ ...draft, requires_user_confirmation: false })).toBeNull();
    expect(parseAssistantBlock({ ...draft, schedule: { ...schedule, frequency: "daily" } })).toBeNull();
    expect(parseAssistantBlock({ ...draft, schedule: { ...schedule, start_date: "2026-02-30" } })).toBeNull();
    expect(parseAssistantBlock({ ...draft, schedule: { ...schedule, timezone: "Not/AZone" } })).toBeNull();
    expect(parseAssistantBlock({ ...draft, schedule: { ...schedule, interval: 5 } })).toBeNull();
    expect(parseAssistantBlock({ ...draft, schedule: { ...schedule, reminder_minutes: 1441 } })).toBeNull();
    expect(parseAssistantBlock({ ...draft, action: { method: "POST", url: "/api/routines" } })).toBeNull();
  });
});
