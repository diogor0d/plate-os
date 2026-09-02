import "fake-indexeddb/auto";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import type { MealLogCreate } from "../types";
import {
  db,
  discardOccurrenceCompletionAttempt,
  discardPendingMealLog,
  enqueueMealLog,
  EXPECTED_OWNER_HEADER,
  flushOccurrenceCompletionAttempts,
  flushPendingMealLogs,
  getMealLogQueueState,
  getOccurrenceCompletionState,
  normalizePendingMealLog,
  recordOccurrenceCompletionAttempt,
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
  await db.occurrenceCompletionAttempts.clear();
});

afterAll(() => db.close());

describe("offline meal queue", () => {
  const accountA = "11111111-1111-4111-8111-111111111111";
  const accountB = "22222222-2222-4222-8222-222222222222";

  it("serializes overlapping flush calls", async () => {
    await enqueueMealLog(accountA, payload("Oats"));
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response("{}", { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const [first, second] = await Promise.all([
      flushPendingMealLogs(accountA),
      flushPendingMealLogs(accountA),
    ]);

    expect(first).toBe(1);
    expect(second).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(await db.pendingMealLogs.count()).toBe(0);
  });

  it("retains permanent failures and continues with later valid entries", async () => {
    await enqueueMealLog(accountA, payload("Invalid"));
    await enqueueMealLog(accountA, payload("Valid"));
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

    expect(await flushPendingMealLogs(accountA)).toBe(1);
    const state = await getMealLogQueueState(accountA);
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
      ownerUserId: accountA,
      payload: legacy as MealLogCreate,
      createdAt,
      status: "pending",
    });

    const [first, second] = await Promise.all([
      normalizePendingMealLog(accountA, id),
      normalizePendingMealLog(accountA, id),
    ]);

    expect(first?.payload.client_mutation_id).toBe(second?.payload.client_mutation_id);
    expect(first?.payload.logged_at).toBe("2026-08-24T23:55:00.000Z");
  });

  it("flushes and reports only the selected account's owned rows", async () => {
    await enqueueMealLog(accountA, payload("Account A"));
    await enqueueMealLog(accountB, payload("Account B"));
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response("{}", { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    expect(await flushPendingMealLogs(accountA)).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string).custom_name).toBe("Account A");
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get(EXPECTED_OWNER_HEADER)).toBe(accountA);
    expect((await getMealLogQueueState(accountA)).pending).toBe(0);
    expect((await getMealLogQueueState(accountB)).pending).toBe(1);

    const remaining = await db.pendingMealLogs.toArray();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].ownerUserId).toBe(accountB);
  });

  it("stops and leaves the owner row pending when the cookie account changes mid-flush", async () => {
    await enqueueMealLog(accountA, payload("First"));
    await enqueueMealLog(accountA, payload("Second"));
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 201 }))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({ detail: "Authenticated account does not match queued meal owner" }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ));
    vi.stubGlobal("fetch", fetchMock);

    expect(await flushPendingMealLogs(accountA)).toBe(1);

    const state = await getMealLogQueueState(accountA);
    expect(state.pending).toBe(1);
    expect(state.failed).toHaveLength(0);
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get(EXPECTED_OWNER_HEADER)).toBe(accountA);
    const remaining = await db.pendingMealLogs.toArray();
    expect(remaining[0].payload.custom_name).toBe("Second");
  });

  it("quarantines ownerless legacy rows without assigning or flushing them", async () => {
    const legacyPayload = payload("Ownerless legacy");
    const mutationId = legacyPayload.client_mutation_id;
    const loggedAt = legacyPayload.logged_at;
    const id = await db.pendingMealLogs.add({
      payload: legacyPayload,
      createdAt: Date.parse("2026-08-24T23:55:00.000Z"),
      status: "pending",
    } as never);
    const fetchMock = vi.fn(async () => new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    expect(await flushPendingMealLogs(accountA)).toBe(0);
    expect(fetchMock).not.toHaveBeenCalled();

    const state = await getMealLogQueueState(accountA);
    expect(state.pending).toBe(0);
    expect(state.failed).toHaveLength(1);
    expect(state.failed[0].ownerUserId).toBeUndefined();
    expect(state.failed[0].payload.client_mutation_id).toBe(mutationId);
    expect(state.failed[0].payload.logged_at).toBe(loggedAt);
    expect(state.failed[0].lastError).toContain("without an account owner");

    await discardPendingMealLog(accountA, id);
    expect(await db.pendingMealLogs.get(id)).toBeUndefined();
  });

  it("does not normalize or discard another account's row", async () => {
    await enqueueMealLog(accountB, payload("Account B"));
    const row = await db.pendingMealLogs.where("ownerUserId").equals(accountB).first();

    expect(await normalizePendingMealLog(accountA, row!.id!)).toBeUndefined();
    await discardPendingMealLog(accountA, row!.id!);
    expect(await db.pendingMealLogs.get(row!.id!)).toBeDefined();
  });

  it("only queues network, rate-limit, and server failures", () => {
    expect(shouldQueueMealLogError(new TypeError("network"))).toBe(true);
    expect(shouldQueueMealLogError(new ApiError(429, "slow down"))).toBe(true);
    expect(shouldQueueMealLogError(new ApiError(503, "down"))).toBe(true);
    expect(shouldQueueMealLogError(new ApiError(401, "login"))).toBe(false);
    expect(shouldQueueMealLogError(new ApiError(422, "invalid"))).toBe(false);
  });

  it("durably resumes exact occurrence meal and completion mutations after ambiguity", async () => {
    const first = payload("Rice");
    const second = payload("Chicken");
    const completionMutationId = crypto.randomUUID();
    await recordOccurrenceCompletionAttempt(accountA, {
      id: crypto.randomUUID(),
      occurrenceId: "occurrence-1",
      mealPayloads: [first, second],
      confirmedAt: "2026-09-02T12:00:00.000Z",
      completionMutationId,
    });
    const interruptedFetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 201 }))
      .mockRejectedValueOnce(new TypeError("network"));
    vi.stubGlobal("fetch", interruptedFetch);

    expect(await flushOccurrenceCompletionAttempts(accountA)).toBe(0);
    expect((await getOccurrenceCompletionState(accountA)).pending).toBe(1);

    const resumedFetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 201 }))
      .mockResolvedValueOnce(new Response("{}", { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: accountA }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", resumedFetch);

    expect(await flushOccurrenceCompletionAttempts(accountA)).toBe(1);
    expect(await db.occurrenceCompletionAttempts.count()).toBe(0);
    expect(JSON.parse(resumedFetch.mock.calls[0][1]?.body as string).client_mutation_id)
      .toBe(first.client_mutation_id);
    expect(JSON.parse(resumedFetch.mock.calls[1][1]?.body as string).client_mutation_id)
      .toBe(second.client_mutation_id);
    expect(new Headers(resumedFetch.mock.calls[0][1]?.headers).get(EXPECTED_OWNER_HEADER))
      .toBe(accountA);
    const completionBody = JSON.parse(resumedFetch.mock.calls[3][1]?.body as string) as {
      client_mutation_id: string;
      meal_log_client_mutation_ids: string[];
    };
    expect(completionBody.client_mutation_id).toBe(completionMutationId);
    expect(completionBody.meal_log_client_mutation_ids).toEqual([
      first.client_mutation_id,
      second.client_mutation_id,
    ]);
  });

  it("keeps an occurrence pending if identity changes before completion", async () => {
    await recordOccurrenceCompletionAttempt(accountA, {
      id: "switched-attempt",
      occurrenceId: "switched-occurrence",
      mealPayloads: [payload("Meal")],
      confirmedAt: "2026-09-02T12:00:00.000Z",
      completionMutationId: crypto.randomUUID(),
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: accountB }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);

    expect(await flushOccurrenceCompletionAttempts(accountA)).toBe(0);
    const state = await getOccurrenceCompletionState(accountA);
    expect(state.pending).toBe(1);
    expect(state.failed).toHaveLength(0);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retains a permanent occurrence failure without blocking later attempts", async () => {
    await recordOccurrenceCompletionAttempt(accountA, {
      id: "attempt-1",
      occurrenceId: "occurrence-1",
      mealPayloads: [payload("Invalid")],
      confirmedAt: "2026-09-02T12:00:00.000Z",
      completionMutationId: crypto.randomUUID(),
    });
    await recordOccurrenceCompletionAttempt(accountA, {
      id: "attempt-2",
      occurrenceId: "occurrence-2",
      mealPayloads: [payload("Valid")],
      confirmedAt: "2026-09-02T12:01:00.000Z",
      completionMutationId: crypto.randomUUID(),
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "invalid quantity" }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response("{}", { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: accountA }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    expect(await flushOccurrenceCompletionAttempts(accountA)).toBe(1);
    const state = await getOccurrenceCompletionState(accountA);
    expect(state.pending).toBe(0);
    expect(state.failed).toHaveLength(1);
    expect(state.failed[0].id).toBe("attempt-1");
    expect(state.failed[0].lastError).toBe("invalid quantity");
  });

  it("does not replay or discard another account's occurrence attempt", async () => {
    await recordOccurrenceCompletionAttempt(accountB, {
      id: "account-b-attempt",
      occurrenceId: "occurrence-b",
      mealPayloads: [payload("Account B")],
      confirmedAt: "2026-09-02T12:00:00.000Z",
      completionMutationId: crypto.randomUUID(),
    });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    expect(await flushOccurrenceCompletionAttempts(accountA)).toBe(0);
    await discardOccurrenceCompletionAttempt(accountA, "account-b-attempt");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await db.occurrenceCompletionAttempts.get("account-b-attempt")).toBeDefined();
  });
});
