/**
 * Offline-first queue (brief constraint #4): meal-log posts that fail due to
 * connectivity are stored in IndexedDB (via Dexie) and flushed on mount and
 * whenever connectivity returns. 4xx validation failures are dropped rather
 * than retried forever (poison-pill protection).
 */
import Dexie, { type Table } from "dexie";
import type { MealLogCreate } from "../types";

export interface PendingMealLog {
  id?: number;
  payload: MealLogCreate;
  createdAt: number;
}

class PlateOSDB extends Dexie {
  pendingMealLogs!: Table<PendingMealLog, number>;

  constructor() {
    super("plateos");
    this.version(1).stores({
      pendingMealLogs: "++id, createdAt",
    });
  }
}

export const db = new PlateOSDB();

export async function enqueueMealLog(payload: MealLogCreate): Promise<void> {
  await db.pendingMealLogs.add({ payload, createdAt: Date.now() });
}

/** Returns the number of successfully flushed entries. */
export async function flushPendingMealLogs(): Promise<number> {
  const pending = await db.pendingMealLogs.orderBy("createdAt").toArray();
  let sent = 0;
  for (const item of pending) {
    if (item.id === undefined) continue;
    try {
      const res = await fetch("/api/meal-logs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(item.payload),
      });
      if (res.ok) {
        await db.pendingMealLogs.delete(item.id);
        sent++;
      } else if (res.status >= 400 && res.status < 500 && res.status !== 401 && res.status !== 429) {
        await db.pendingMealLogs.delete(item.id); // permanent rejection
      } else {
        break; // transient (401/429/5xx): retry on next flush
      }
    } catch {
      break; // offline again: retry on next flush
    }
  }
  return sent;
}
