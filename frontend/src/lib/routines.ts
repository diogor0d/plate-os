import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Per100, SourceType } from "./types";
import type { StableMutation } from "./products";

export type RoutineMode = "rough" | "defined";
export type ScheduleFrequency = "daily" | "weekly";
export type OccurrenceStatus = "scheduled" | "completed" | "skipped";
export type OccurrenceState = "upcoming" | "due" | "missed" | "completed" | "skipped";

export interface RoutineProduct {
  id: string;
  barcode: string | null;
  name: string;
  brand: string | null;
  serving_unit: string;
  calories_per_100: number;
  protein_per_100: number;
  carbs_per_100: number;
  fat_per_100: number;
  fiber_per_100: number;
  nutrition_source: "manual" | "open_food_facts" | "vision_label";
  accepted_at: string;
  updated_at: string;
  version: number;
  archived_at: string | null;
}

export interface RoutineItem {
  position: number;
  quantity_g: number;
  product: RoutineProduct;
}

export interface Routine {
  id: string;
  title: string;
  mode: RoutineMode;
  rough_text: string | null;
  version: number;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  items: RoutineItem[];
}

export interface RoutineWrite {
  client_mutation_id: string;
  title: string;
  mode: RoutineMode;
  rough_text: string | null;
  items: Array<{ food_item_id: string; quantity_g: number }>;
  expected_version: number | null;
}

export interface Schedule {
  id: string;
  routine_id: string;
  local_time: string;
  timezone: string;
  frequency: ScheduleFrequency;
  interval: number;
  iso_weekdays: number[];
  start_date: string;
  end_date: string | null;
  reminder_minutes: number | null;
  enabled: boolean;
  version: number;
}

export interface ScheduleCreate {
  client_mutation_id: string;
  local_time: string;
  timezone: string;
  frequency: ScheduleFrequency;
  interval: number;
  iso_weekdays: number[];
  start_date: string;
  end_date: string | null;
  reminder_minutes: number | null;
}

export interface Occurrence {
  id: string;
  routine: Routine;
  schedule_id: string;
  scheduled_at: string;
  scheduled_local_date: string;
  schedule_timezone: string;
  time_resolution: string;
  status: OccurrenceStatus;
  state: OccurrenceState;
}

export interface Agenda {
  server_now: string;
  display_timezone: string;
  occurrences: Occurrence[];
  next_due_at: string | null;
  countdown_seconds: number | null;
}

export interface RoutineDraft {
  title: string;
  mode: RoutineMode;
  roughText: string;
  items: Array<{ product: RoutineProduct; quantityG: number }>;
}

/** Structurally matches ProposalCardItem without coupling the data layer to a component. */
export interface RoutineProposalItem {
  name: string;
  per100: Per100;
  quantityG: number;
  foodItemId: string;
  sourceType: SourceType;
}

export interface RoutineMealProposal {
  occurrence: Occurrence;
  items: RoutineProposalItem[];
  /**
   * Call only after every meal mutation is persisted by the server. Queued
   * offline writes cannot complete an occurrence until they have replayed.
   */
  complete: (mealLogClientMutationIds: string[], confirmedAt?: string) => Promise<void>;
}

export interface AgendaRange {
  start?: string;
  end?: string;
  days?: number;
}

export function validateRoutineDraft(draft: RoutineDraft): string | null {
  if (!draft.title.trim() || draft.title.trim().length > 100) {
    return "Use a routine title between 1 and 100 characters.";
  }
  if (draft.mode === "rough") {
    if (!draft.roughText.trim() || draft.roughText.trim().length > 2000) {
      return "Rough routines need a description of up to 2,000 characters.";
    }
    return null;
  }
  if (draft.items.length < 1 || draft.items.length > 8) {
    return "Defined routines need between 1 and 8 accepted products.";
  }
  if (new Set(draft.items.map((item) => item.product.id)).size !== draft.items.length) {
    return "Each product can appear only once in a routine.";
  }
  if (draft.items.some((item) => !validQuantity(item.quantityG))) {
    return "Quantities must be 0.01-10,000 g with at most 2 decimals.";
  }
  return null;
}

export function buildRoutineWrite(
  draft: RoutineDraft,
  clientMutationId: string,
  expectedVersion: number | null,
): RoutineWrite {
  return {
    client_mutation_id: clientMutationId,
    title: draft.title.trim(),
    mode: draft.mode,
    rough_text: draft.mode === "rough" ? draft.roughText.trim() : null,
    items: draft.mode === "defined"
      ? draft.items.map((item) => ({ food_item_id: item.product.id, quantity_g: item.quantityG }))
      : [],
    expected_version: expectedVersion,
  };
}

export function validateSchedule(input: Omit<ScheduleCreate, "client_mutation_id">): string | null {
  if (!/^([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(input.local_time)) {
    return "Choose a valid local time.";
  }
  if (!Number.isInteger(input.interval) || input.interval < 1 || input.interval > 4) {
    return "The schedule interval must be between 1 and 4.";
  }
  if (!isIanaTimezone(input.timezone)) return "Use a valid IANA timezone.";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(input.start_date)) return "Choose a start date.";
  if (input.end_date !== null && !/^\d{4}-\d{2}-\d{2}$/.test(input.end_date)) {
    return "Choose a valid end date.";
  }
  if (input.end_date && input.end_date < input.start_date) {
    return "The end date cannot precede the start date.";
  }
  const weekdays = new Set(input.iso_weekdays);
  if (weekdays.size !== input.iso_weekdays.length || input.iso_weekdays.some((day) => day < 1 || day > 7)) {
    return "Weekdays must be unique values from Monday through Sunday.";
  }
  if (input.frequency === "daily" && input.iso_weekdays.length) {
    return "Daily schedules cannot select weekdays.";
  }
  if (input.frequency === "weekly" && !input.iso_weekdays.length) {
    return "Select at least one weekday for a weekly schedule.";
  }
  if (input.reminder_minutes !== null && (
    !Number.isInteger(input.reminder_minutes) || input.reminder_minutes < 0 || input.reminder_minutes > 1440
  )) {
    return "Reminder lead time must be 0-1,440 minutes.";
  }
  return null;
}

export function isIanaTimezone(value: string): boolean {
  if (!value.trim()) return false;
  try {
    new Intl.DateTimeFormat("en", { timeZone: value }).format();
    return true;
  } catch {
    return false;
  }
}

export function buildAgendaQuery(range: AgendaRange = {}): string {
  const params = new URLSearchParams();
  if (range.start) params.set("start", range.start);
  if (range.end) params.set("end", range.end);
  if (!range.start && !range.end) params.set("days", String(range.days ?? 7));
  return params.toString();
}

/** Reuses a UUID while retrying an unchanged operation, and rotates it when its payload changes. */
export function stableRoutineMutation(
  current: StableMutation | null,
  fingerprint: string,
  createId: () => string = () => crypto.randomUUID(),
): StableMutation {
  return current?.fingerprint === fingerprint ? current : { fingerprint, id: createId() };
}

export const routineFingerprint = (value: object): string => JSON.stringify(value);

export async function listRoutines(includeArchived = false): Promise<Routine[]> {
  return api<Routine[]>(`/api/routines?include_archived=${String(includeArchived)}`);
}

export async function saveRoutine(
  draft: RoutineDraft,
  mutationId: string,
  routine?: Routine,
): Promise<Routine> {
  const body = buildRoutineWrite(draft, mutationId, routine?.version ?? null);
  return api<Routine>(routine ? `/api/routines/${encodeURIComponent(routine.id)}` : "/api/routines", {
    method: routine ? "PUT" : "POST",
    body: JSON.stringify(body),
  });
}

export async function archiveRoutine(routine: Routine, mutationId: string): Promise<Routine> {
  return api<Routine>(`/api/routines/${encodeURIComponent(routine.id)}/archive`, {
    method: "POST",
    body: JSON.stringify({ client_mutation_id: mutationId, expected_version: routine.version }),
  });
}

export async function listSchedules(routineId: string): Promise<Schedule[]> {
  return api<Schedule[]>(`/api/routines/${encodeURIComponent(routineId)}/schedules`);
}

export async function createSchedule(
  routineId: string,
  value: Omit<ScheduleCreate, "client_mutation_id">,
  mutationId: string,
): Promise<Schedule> {
  return api<Schedule>(`/api/routines/${encodeURIComponent(routineId)}/schedules`, {
    method: "POST",
    body: JSON.stringify({ ...value, client_mutation_id: mutationId }),
  });
}

export async function setScheduleEnabled(
  schedule: Schedule,
  enabled: boolean,
  mutationId: string,
): Promise<Schedule> {
  return api<Schedule>(`/api/schedules/${encodeURIComponent(schedule.id)}`, {
    method: "PATCH",
    body: JSON.stringify({
      client_mutation_id: mutationId,
      expected_version: schedule.version,
      enabled,
    }),
  });
}

export async function completeOccurrence(
  occurrenceId: string,
  mealLogClientMutationIds: string[],
  mutationId: string,
  confirmedAt = new Date().toISOString(),
): Promise<Occurrence> {
  return api<Occurrence>(`/api/occurrences/${encodeURIComponent(occurrenceId)}/complete`, {
    method: "POST",
    body: JSON.stringify({
      client_mutation_id: mutationId,
      confirmed_at: confirmedAt,
      meal_log_client_mutation_ids: mealLogClientMutationIds,
    }),
  });
}

export async function skipOccurrence(
  occurrenceId: string,
  mutationId: string,
  actedAt = new Date().toISOString(),
): Promise<Occurrence> {
  return api<Occurrence>(`/api/occurrences/${encodeURIComponent(occurrenceId)}/skip`, {
    method: "POST",
    body: JSON.stringify({ client_mutation_id: mutationId, acted_at: actedAt }),
  });
}

export function fetchAgenda(range: AgendaRange = {}): Promise<Agenda> {
  const query = buildAgendaQuery(range);
  return api<Agenda>(`/api/agenda/refresh?${query}`, { method: "POST" });
}

export function useAgenda(range: AgendaRange = {}) {
  const query = buildAgendaQuery(range);
  return useQuery({
    queryKey: ["agenda", query],
    queryFn: () => fetchAgenda(range),
  });
}

export function countdownAt(agenda: Agenda, elapsedSeconds = 0): number | null {
  if (agenda.countdown_seconds === null) return null;
  return Math.max(0, agenda.countdown_seconds - Math.max(0, Math.floor(elapsedSeconds)));
}

export function useAgendaCountdown(agenda: Agenda | undefined): number | null {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const startedAt = Date.now();
    setElapsed(0);
    if (agenda?.countdown_seconds === null || agenda === undefined) return;
    const timer = window.setInterval(() => setElapsed((Date.now() - startedAt) / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [agenda]);
  return agenda ? countdownAt(agenda, elapsed) : null;
}

export function formatCountdown(seconds: number | null): string {
  if (seconds === null) return "No upcoming meals";
  if (seconds <= 0) return "Due now";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export function timeResolutionMessage(resolution: string): string {
  if (resolution === "ambiguous-earlier") {
    return "This local time occurs twice after the DST change; PlateOS uses the earlier occurrence.";
  }
  if (resolution === "nonexistent-shift-forward") {
    return "This local time did not exist during the DST change; PlateOS shifted it forward to the first valid time.";
  }
  if (resolution === "exact") return "Scheduled at the exact requested local time.";
  return `Time resolved by the server (${resolution}).`;
}

export function routineToProposalItems(routine: Routine): RoutineProposalItem[] {
  if (routine.mode !== "defined") return [];
  return routine.items.map(({ product, quantity_g }) => ({
    name: product.brand ? `${product.brand} ${product.name}` : product.name,
    per100: {
      calories: product.calories_per_100,
      protein_g: product.protein_per_100,
      carbs_g: product.carbs_per_100,
      fat_g: product.fat_per_100,
      fiber_g: product.fiber_per_100,
    },
    quantityG: quantity_g,
    foodItemId: product.id,
    sourceType: product.nutrition_source === "open_food_facts" ? "barcode" : product.nutrition_source,
  }));
}

function validQuantity(value: number): boolean {
  return Number.isFinite(value) && value >= 0.01 && value <= 10000
    && Math.abs(Math.round(value * 100) - value * 100) < 1e-8;
}
