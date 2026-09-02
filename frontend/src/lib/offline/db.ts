/**
 * Offline-first queue (brief constraint #4): meal-log posts that fail due to
 * connectivity are stored in IndexedDB (via Dexie) and flushed on mount and
 * whenever connectivity returns. Permanent 4xx failures remain visible in a
 * failed state and do not block later rows (poison-pill protection).
 */
import Dexie, { type Table } from "dexie";
import { ApiError } from "../api";
import type { MealLogCreate } from "../types";

export type PendingMealLogStatus = "pending" | "failed";

export interface PendingMealLog {
  id?: number;
  ownerUserId: string;
  payload: MealLogCreate;
  createdAt: number;
  status: PendingMealLogStatus;
  lastError?: string;
}

export type OccurrenceCompletionStatus = "pending" | "failed";

export interface OccurrenceCompletionAttempt {
  id: string;
  ownerUserId: string;
  occurrenceId: string;
  mealPayloads: MealLogCreate[];
  confirmedAt: string;
  completionMutationId: string;
  createdAt: number;
  status: OccurrenceCompletionStatus;
  lastError?: string;
}

type LegacyMealLogCreate = Omit<MealLogCreate, "logged_at" | "client_mutation_id"> &
  Partial<Pick<MealLogCreate, "logged_at" | "client_mutation_id">>;

interface LegacyPendingMealLog
  extends Omit<PendingMealLog, "ownerUserId" | "payload" | "status"> {
  ownerUserId?: string;
  payload: LegacyMealLogCreate;
  status?: PendingMealLogStatus;
}

export const MEAL_LOG_QUEUE_CHANGED_EVENT = "plateos:meal-log-queue-changed";
export const EXPECTED_OWNER_HEADER = "X-PlateOS-Expected-User-ID";
const LEGACY_QUARANTINE_ERROR =
  "Queued by an earlier PlateOS version without an account owner. Discard and log again.";

function notifyQueueChanged() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(MEAL_LOG_QUEUE_CHANGED_EVENT));
  }
}

class PlateOSDB extends Dexie {
  pendingMealLogs!: Table<PendingMealLog, number>;
  occurrenceCompletionAttempts!: Table<OccurrenceCompletionAttempt, string>;

  constructor() {
    super("plateos");
    this.version(1).stores({
      pendingMealLogs: "++id, createdAt",
    });
    this.version(2)
      .stores({
        pendingMealLogs: "++id, status, createdAt",
      })
      .upgrade((transaction) =>
        transaction
          .table<LegacyPendingMealLog, number>("pendingMealLogs")
          .toCollection()
          .modify((item) => {
            item.status ??= "pending";
            item.payload.logged_at ??= new Date(item.createdAt).toISOString();
            item.payload.client_mutation_id ??= crypto.randomUUID();
          }),
      );
    this.version(3)
      .stores({
        pendingMealLogs:
          "++id, ownerUserId, status, createdAt, [ownerUserId+createdAt], [ownerUserId+status]",
      })
      .upgrade((transaction) =>
        transaction
          .table<LegacyPendingMealLog, number>("pendingMealLogs")
          .toCollection()
          .modify((item) => {
            if (!item.ownerUserId) {
              item.status = "failed";
              item.lastError ??= LEGACY_QUARANTINE_ERROR;
            }
          }),
      );
    this.version(4).stores({
      pendingMealLogs:
        "++id, ownerUserId, status, createdAt, [ownerUserId+createdAt], [ownerUserId+status]",
      occurrenceCompletionAttempts:
        "id, ownerUserId, occurrenceId, status, createdAt, &[ownerUserId+occurrenceId], [ownerUserId+createdAt], [ownerUserId+status]",
    });
  }
}

export const db = new PlateOSDB();

function requireAccountId(accountId: string): void {
  if (!accountId.trim()) throw new Error("accountId is required");
}

async function quarantineLegacyMealLogs(): Promise<void> {
  await db.pendingMealLogs
    .filter((item) => !(item as LegacyPendingMealLog).ownerUserId)
    .modify((item) => {
      item.status = "failed";
      item.lastError ??= LEGACY_QUARANTINE_ERROR;
    });
}

export async function enqueueMealLog(
  accountId: string,
  payload: MealLogCreate,
): Promise<void> {
  requireAccountId(accountId);
  await db.pendingMealLogs.add({
    ownerUserId: accountId,
    payload,
    createdAt: Date.now(),
    status: "pending",
  });
  notifyQueueChanged();
}

export function shouldQueueMealLogError(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status === 429 || error.status >= 500;
}

export async function normalizePendingMealLog(
  accountId: string,
  id: number,
): Promise<PendingMealLog | undefined> {
  requireAccountId(accountId);
  return db.transaction("rw", db.pendingMealLogs, async () => {
    const current = (await db.pendingMealLogs.get(id)) as
      | (LegacyPendingMealLog & { ownerUserId?: string })
      | undefined;
    if (!current || current.ownerUserId !== accountId) return undefined;

    const normalized: PendingMealLog = {
      ...current,
      ownerUserId: accountId,
      status: current.status ?? "pending",
      payload: {
        ...current.payload,
        logged_at: current.payload.logged_at ?? new Date(current.createdAt).toISOString(),
        client_mutation_id: current.payload.client_mutation_id ?? crypto.randomUUID(),
      },
    };
    await db.pendingMealLogs.put(normalized);
    return normalized;
  });
}

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail !== undefined) return JSON.stringify(body.detail);
  } catch {
    // Keep the HTTP fallback for non-JSON responses.
  }
  return `HTTP ${response.status}`;
}

function isSessionMismatch(status: number, detail: string): boolean {
  return status === 409 && detail === "Authenticated account does not match queued meal owner";
}

function isTransientStatus(status: number): boolean {
  return status === 401 || status === 429 || status >= 500;
}

async function runFlush(accountId: string): Promise<number> {
  await quarantineLegacyMealLogs();
  const pending = await db.pendingMealLogs.where("ownerUserId").equals(accountId).sortBy("createdAt");
  let sent = 0;
  for (const queued of pending) {
    if (queued.id === undefined || queued.status === "failed") continue;
    const item = await normalizePendingMealLog(accountId, queued.id);
    if (!item || item.status === "failed") continue;
    try {
      const res = await fetch("/api/meal-logs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [EXPECTED_OWNER_HEADER]: accountId,
        },
        credentials: "same-origin",
        body: JSON.stringify(item.payload),
      });
      if (res.ok) {
        await db.pendingMealLogs.delete(queued.id);
        sent++;
      } else {
        const detail = await responseDetail(res);
        if (isSessionMismatch(res.status, detail) || isTransientStatus(res.status)) break;
        await db.pendingMealLogs.update(queued.id, {
          status: "failed",
          lastError: detail,
        });
      }
    } catch {
      break; // offline again: retry on next flush
    }
  }
  notifyQueueChanged();
  return sent;
}

export async function recordOccurrenceCompletionAttempt(
  accountId: string,
  attempt: Omit<OccurrenceCompletionAttempt, "ownerUserId" | "createdAt" | "status">,
): Promise<OccurrenceCompletionAttempt> {
  requireAccountId(accountId);
  const stored = await db.transaction("rw", db.occurrenceCompletionAttempts, async () => {
    const existing = await db.occurrenceCompletionAttempts
      .where("[ownerUserId+occurrenceId]")
      .equals([accountId, attempt.occurrenceId])
      .first();
    if (existing) return existing;
    const created: OccurrenceCompletionAttempt = {
      ...attempt,
      ownerUserId: accountId,
      createdAt: Date.now(),
      status: "pending",
    };
    await db.occurrenceCompletionAttempts.add(created);
    return created;
  });
  notifyQueueChanged();
  return stored;
}

type AttemptResult = "completed" | "continue" | "stop";

async function markAttemptFailed(
  attempt: OccurrenceCompletionAttempt,
  lastError: string,
): Promise<AttemptResult> {
  await db.occurrenceCompletionAttempts.update(attempt.id, { status: "failed", lastError });
  return "continue";
}

async function replayOccurrenceAttempt(
  accountId: string,
  attempt: OccurrenceCompletionAttempt,
): Promise<AttemptResult> {
  for (const payload of attempt.mealPayloads) {
    try {
      const response = await fetch("/api/meal-logs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [EXPECTED_OWNER_HEADER]: accountId,
        },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const detail = await responseDetail(response);
        if (isSessionMismatch(response.status, detail) || isTransientStatus(response.status)) {
          return "stop";
        }
        return markAttemptFailed(attempt, detail);
      }
    } catch {
      return "stop";
    }
  }

  try {
    const identity = await fetch("/api/auth/me", { credentials: "same-origin" });
    if (!identity.ok) {
      return isTransientStatus(identity.status)
        ? "stop"
        : markAttemptFailed(attempt, await responseDetail(identity));
    }
    const authenticated = (await identity.json()) as { id?: unknown };
    if (authenticated.id !== accountId) return "stop";

    const response = await fetch(
      `/api/occurrences/${encodeURIComponent(attempt.occurrenceId)}/complete`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [EXPECTED_OWNER_HEADER]: accountId,
        },
        credentials: "same-origin",
        body: JSON.stringify({
          client_mutation_id: attempt.completionMutationId,
          confirmed_at: attempt.confirmedAt,
          meal_log_client_mutation_ids: attempt.mealPayloads.map(
            (payload) => payload.client_mutation_id,
          ),
        }),
      },
    );
    if (response.ok) {
      await db.occurrenceCompletionAttempts.delete(attempt.id);
      return "completed";
    }
    const detail = await responseDetail(response);
    if (isSessionMismatch(response.status, detail) || isTransientStatus(response.status)) {
      return "stop";
    }
    return markAttemptFailed(attempt, detail);
  } catch {
    return "stop";
  }
}

async function runOccurrenceFlush(accountId: string): Promise<number> {
  const attempts = await db.occurrenceCompletionAttempts
    .where("ownerUserId")
    .equals(accountId)
    .sortBy("createdAt");
  let completed = 0;
  for (const attempt of attempts) {
    if (attempt.status === "failed") continue;
    const result = await replayOccurrenceAttempt(accountId, attempt);
    if (result === "stop") break;
    if (result === "completed") completed++;
  }
  notifyQueueChanged();
  return completed;
}

const activeOccurrenceFlushes = new Map<string, Promise<number>>();

export function flushOccurrenceCompletionAttempts(accountId: string): Promise<number> {
  requireAccountId(accountId);
  const active = activeOccurrenceFlushes.get(accountId);
  if (active) return active;
  const flush = runOccurrenceFlush(accountId).finally(() => {
    activeOccurrenceFlushes.delete(accountId);
  });
  activeOccurrenceFlushes.set(accountId, flush);
  return flush;
}

export async function getOccurrenceCompletionState(accountId: string): Promise<{
  pending: number;
  failed: OccurrenceCompletionAttempt[];
}> {
  requireAccountId(accountId);
  const attempts = await db.occurrenceCompletionAttempts
    .where("ownerUserId")
    .equals(accountId)
    .sortBy("createdAt");
  return {
    pending: attempts.filter((attempt) => attempt.status === "pending").length,
    failed: attempts.filter((attempt) => attempt.status === "failed"),
  };
}

export async function discardOccurrenceCompletionAttempt(
  accountId: string,
  id: string,
): Promise<void> {
  requireAccountId(accountId);
  const deleted = await db.transaction("rw", db.occurrenceCompletionAttempts, async () => {
    const attempt = await db.occurrenceCompletionAttempts.get(id);
    if (!attempt || attempt.ownerUserId !== accountId) return false;
    await db.occurrenceCompletionAttempts.delete(id);
    return true;
  });
  if (deleted) notifyQueueChanged();
}

const activeFlushes = new Map<string, Promise<number>>();

/** Returns the number of successfully flushed entries. */
export function flushPendingMealLogs(accountId: string): Promise<number> {
  requireAccountId(accountId);
  const activeFlush = activeFlushes.get(accountId);
  if (activeFlush) return activeFlush;
  const flush = runFlush(accountId).finally(() => {
    activeFlushes.delete(accountId);
  });
  activeFlushes.set(accountId, flush);
  return flush;
}

export async function getMealLogQueueState(accountId: string): Promise<{
  pending: number;
  failed: PendingMealLog[];
}> {
  requireAccountId(accountId);
  await quarantineLegacyMealLogs();
  const allItems = await db.pendingMealLogs.orderBy("createdAt").toArray();
  const items = allItems.filter(
    (item) => item.ownerUserId === accountId || !(item as LegacyPendingMealLog).ownerUserId,
  );
  return {
    pending: items.filter((item) => item.status !== "failed").length,
    failed: items.filter((item) => item.status === "failed"),
  };
}

export async function discardPendingMealLog(accountId: string, id: number): Promise<void> {
  requireAccountId(accountId);
  const deleted = await db.transaction("rw", db.pendingMealLogs, async () => {
    const item = await db.pendingMealLogs.get(id);
    if (item && (item.ownerUserId === accountId || !(item as LegacyPendingMealLog).ownerUserId)) {
      await db.pendingMealLogs.delete(id);
      return true;
    }
    return false;
  });
  if (deleted) notifyQueueChanged();
}
