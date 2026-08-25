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
  payload: MealLogCreate;
  createdAt: number;
  status: PendingMealLogStatus;
  lastError?: string;
}

type LegacyMealLogCreate = Omit<MealLogCreate, "logged_at" | "client_mutation_id"> &
  Partial<Pick<MealLogCreate, "logged_at" | "client_mutation_id">>;

interface LegacyPendingMealLog extends Omit<PendingMealLog, "payload" | "status"> {
  payload: LegacyMealLogCreate;
  status?: PendingMealLogStatus;
}

export const MEAL_LOG_QUEUE_CHANGED_EVENT = "plateos:meal-log-queue-changed";

function notifyQueueChanged() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(MEAL_LOG_QUEUE_CHANGED_EVENT));
  }
}

class PlateOSDB extends Dexie {
  pendingMealLogs!: Table<PendingMealLog, number>;

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
  }
}

export const db = new PlateOSDB();

export async function enqueueMealLog(payload: MealLogCreate): Promise<void> {
  await db.pendingMealLogs.add({ payload, createdAt: Date.now(), status: "pending" });
  notifyQueueChanged();
}

export function shouldQueueMealLogError(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status === 429 || error.status >= 500;
}

export async function normalizePendingMealLog(
  id: number,
): Promise<PendingMealLog | undefined> {
  return db.transaction("rw", db.pendingMealLogs, async () => {
    const current = (await db.pendingMealLogs.get(id)) as
      | (PendingMealLog & { payload: LegacyMealLogCreate; status?: PendingMealLogStatus })
      | undefined;
    if (!current) return undefined;

    const normalized: PendingMealLog = {
      ...current,
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

async function runFlush(): Promise<number> {
  const pending = await db.pendingMealLogs.orderBy("createdAt").toArray();
  let sent = 0;
  for (const queued of pending) {
    if (queued.id === undefined || queued.status === "failed") continue;
    const item = await normalizePendingMealLog(queued.id);
    if (!item || item.status === "failed") continue;
    try {
      const res = await fetch("/api/meal-logs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(item.payload),
      });
      if (res.ok) {
        await db.pendingMealLogs.delete(queued.id);
        sent++;
      } else if (res.status >= 400 && res.status < 500 && res.status !== 401 && res.status !== 429) {
        await db.pendingMealLogs.update(queued.id, {
          status: "failed",
          lastError: await responseDetail(res),
        });
      } else {
        break; // transient (401/429/5xx): retry on next flush
      }
    } catch {
      break; // offline again: retry on next flush
    }
  }
  notifyQueueChanged();
  return sent;
}

let activeFlush: Promise<number> | null = null;

/** Returns the number of successfully flushed entries. */
export function flushPendingMealLogs(): Promise<number> {
  if (activeFlush) return activeFlush;
  activeFlush = runFlush().finally(() => {
    activeFlush = null;
  });
  return activeFlush;
}

export async function getMealLogQueueState(): Promise<{
  pending: number;
  failed: PendingMealLog[];
}> {
  const items = await db.pendingMealLogs.orderBy("createdAt").toArray();
  return {
    pending: items.filter((item) => item.status !== "failed").length,
    failed: items.filter((item) => item.status === "failed"),
  };
}

export async function discardPendingMealLog(id: number): Promise<void> {
  await db.pendingMealLogs.delete(id);
  notifyQueueChanged();
}
