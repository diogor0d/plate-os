import "fake-indexeddb/auto";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import type { MealLogCreate } from "../types";
import {
  db,
  enqueueMealLog,
  flushPendingMealLogs,
  getMealLogQueueState,
  normalizePendingMealLog,
  shouldQueueMealLogError,
} from "./db";

function payload(name: string): MealLogCreate {
  return {
    logged_at: "2026-08-25T12:00:00.000Z",
    client_mutation_id: crypto.randomUUID(),
    custom_name: name,
    quantity_g: 100,
    per100: { calories: 100, protein_g: 1, carbs_g: 2, fat_g: 3, fiber_g: 4 },
    source_type: "manual",
  };
}

beforeEach(async () => {
  vi.restoreAllMocks();
  await db.pendingMealLogs.clear();
});

afterAll(() => db.close());

describe("offline meal queue", () => {
  it("serializes overlapping flush calls", async () => {
    await enqueueMealLog(payload("Oats"));
    const fetchMock = vi.fn(async () => new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    const [first, second] = await Promise.all([
      flushPendingMealLogs(),
      flushPendingMealLogs(),
    ]);

    expect(first).toBe(1);
    expect(second).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(await db.pendingMealLogs.count()).toBe(0);
  });

  it("retains permanent failures and continues with later valid entries", async () => {
    await enqueueMealLog(payload("Invalid"));
    await enqueueMealLog(payload("Valid"));
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "invalid quantity" }), {
          status: 422,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    expect(await flushPendingMealLogs()).toBe(1);
    const state = await getMealLogQueueState();
    expect(state.pending).toBe(0);
    expect(state.failed).toHaveLength(1);
    expect(state.failed[0].payload.custom_name).toBe("Invalid");
    expect(state.failed[0].lastError).toBe("invalid quantity");
  });

  it("normalizes one legacy row atomically", async () => {
    const legacy = payload("Legacy") as Partial<MealLogCreate>;
    delete legacy.logged_at;
    delete legacy.client_mutation_id;
    const createdAt = Date.parse("2026-08-24T23:55:00.000Z");
    const id = await db.pendingMealLogs.add({
      payload: legacy as MealLogCreate,
      createdAt,
      status: "pending",
    });

    const [first, second] = await Promise.all([
      normalizePendingMealLog(id),
      normalizePendingMealLog(id),
    ]);

    expect(first?.payload.client_mutation_id).toBe(second?.payload.client_mutation_id);
    expect(first?.payload.logged_at).toBe("2026-08-24T23:55:00.000Z");
  });

  it("only queues network, rate-limit, and server failures", () => {
    expect(shouldQueueMealLogError(new TypeError("network"))).toBe(true);
    expect(shouldQueueMealLogError(new ApiError(429, "slow down"))).toBe(true);
    expect(shouldQueueMealLogError(new ApiError(503, "down"))).toBe(true);
    expect(shouldQueueMealLogError(new ApiError(401, "login"))).toBe(false);
    expect(shouldQueueMealLogError(new ApiError(422, "invalid"))).toBe(false);
  });
});
