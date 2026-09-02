import { useDeferredValue, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  CalendarClock,
  Check,
  ChevronDown,
  Clock3,
  Edit3,
  Plus,
  RotateCcw,
  Search,
  Utensils,
  X,
} from "lucide-react";
import { ApiError } from "../lib/api";
import { listProducts } from "../lib/products";
import {
  archiveRoutine,
  completeOccurrence,
  createSchedule,
  formatCountdown,
  listRoutines,
  listSchedules,
  routineFingerprint,
  routineToProposalItems,
  saveRoutine,
  setScheduleEnabled,
  skipOccurrence,
  stableRoutineMutation,
  timeResolutionMessage,
  useAgenda,
  useAgendaCountdown,
  validateRoutineDraft,
  validateSchedule,
  type Occurrence,
  type Routine,
  type RoutineDraft,
  type RoutineMealProposal,
  type Schedule,
  type ScheduleCreate,
} from "../lib/routines";
import type { StableMutation } from "../lib/products";
import { Button } from "./ui/button";
import { Card } from "./ui/card";

export interface RoutinesProps {
  timezone?: string;
  /** Receives defined items for a ProposalCard-compatible confirmation flow. */
  onLogMeal?: (proposal: RoutineMealProposal) => void;
  /** Rough routines are planning prompts, never consumed meals. */
  onUseRoughRoutine?: (routine: Routine) => void;
}

const field = "w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-600 focus:outline-none";
const eyebrow = "text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-500";
const WEEKDAYS = [
  [1, "Mon"], [2, "Tue"], [3, "Wed"], [4, "Thu"], [5, "Fri"], [6, "Sat"], [7, "Sun"],
] as const;

function localDate() {
  const date = new Date();
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

function defaultTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function emptyDraft(): RoutineDraft {
  return { title: "", mode: "rough", roughText: "", items: [] };
}

function mutationFor(
  store: React.MutableRefObject<Map<string, StableMutation>>,
  operation: string,
  value: object,
) {
  const fingerprint = routineFingerprint(value);
  const current = store.current.get(operation) ?? null;
  const mutation = stableRoutineMutation(current, fingerprint);
  store.current.set(operation, mutation);
  return mutation.id;
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError && error.status === 409) {
    return `${error.message}. Refresh and review the latest version before retrying.`;
  }
  return error instanceof Error ? error.message : String(error);
}

function formatOccurrenceTime(occurrence: Occurrence) {
  return new Intl.DateTimeFormat(undefined, {
    timeZone: occurrence.schedule_timezone,
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(occurrence.scheduled_at));
}

function AgendaPanel({ onLogMeal, onUseRoughRoutine }: Pick<RoutinesProps, "onLogMeal" | "onUseRoughRoutine">) {
  const qc = useQueryClient();
  const agenda = useAgenda({ days: 14 });
  const countdown = useAgendaCountdown(agenda.data);
  const mutations = useRef(new Map<string, StableMutation>());
  const actionTimes = useRef(new Map<string, string>());
  const [error, setError] = useState<string | null>(null);
  const [workingId, setWorkingId] = useState<string | null>(null);

  const skip = async (occurrence: Occurrence) => {
    const actedAt = actionTimes.current.get(occurrence.id) ?? new Date().toISOString();
    actionTimes.current.set(occurrence.id, actedAt);
    const value = { occurrenceId: occurrence.id, actedAt };
    setWorkingId(occurrence.id);
    setError(null);
    try {
      await skipOccurrence(occurrence.id, mutationFor(mutations, `skip:${occurrence.id}`, value), actedAt);
      actionTimes.current.delete(occurrence.id);
      await qc.invalidateQueries({ queryKey: ["agenda"] });
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setWorkingId(null);
    }
  };

  const log = (occurrence: Occurrence) => {
    if (occurrence.routine.mode === "rough") {
      onUseRoughRoutine?.(occurrence.routine);
      return;
    }
    const items = routineToProposalItems(occurrence.routine);
    let completionConfirmedAt: string | null = null;
    onLogMeal?.({
      occurrence,
      items,
      complete: async (mealLogClientMutationIds, confirmedAt = new Date().toISOString()) => {
        if (!mealLogClientMutationIds.length) throw new Error("At least one persisted meal mutation ID is required.");
        completionConfirmedAt ??= confirmedAt;
        const value = { occurrenceId: occurrence.id, mealLogClientMutationIds, confirmedAt: completionConfirmedAt };
        await completeOccurrence(
          occurrence.id,
          mealLogClientMutationIds,
          mutationFor(mutations, `complete:${occurrence.id}`, value),
          completionConfirmedAt,
        );
        await qc.invalidateQueries({ queryKey: ["agenda"] });
      },
    });
  };

  return (
    <section className="space-y-3" aria-labelledby="agenda-heading">
      <Card className="flex items-center justify-between gap-4 border-emerald-950 bg-emerald-950/10">
        <div>
          <p className={eyebrow}>Next planned meal</p>
          <p className="mt-1 text-xl font-semibold tracking-tight text-emerald-300">{formatCountdown(countdown)}</p>
        </div>
        <Clock3 className="h-7 w-7 text-emerald-500/70" />
      </Card>
      <div className="flex items-end justify-between">
        <div>
          <h2 id="agenda-heading" className="text-base font-semibold">Agenda</h2>
          <p className="mt-1 text-xs text-zinc-500">Server-derived plan in {agenda.data?.display_timezone ?? "your profile timezone"}. Nothing here counts as consumed.</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => void agenda.refetch()} disabled={agenda.isFetching}>
          <RotateCcw className="h-3.5 w-3.5" /> Refresh
        </Button>
      </div>
      {agenda.isLoading && <div className="h-32 animate-pulse rounded-xl bg-zinc-900" />}
      {agenda.error && <p className="rounded-xl border border-red-900/50 p-3 text-sm text-red-300">{errorMessage(agenda.error)}</p>}
      {error && <p className="text-xs text-red-400">{error}</p>}
      {agenda.data?.occurrences.length === 0 && (
        <Card className="py-8 text-center text-sm text-zinc-500">No occurrences in the next 14 days.</Card>
      )}
      <div className="space-y-2">
        {agenda.data?.occurrences.map((occurrence) => {
          const actionable = occurrence.status === "scheduled";
          const adjusted = occurrence.time_resolution !== "exact";
          return (
            <Card key={occurrence.id} className={`space-y-3 ${occurrence.state === "due" ? "border-emerald-700/60" : ""}`}>
              <div className="flex items-start gap-3">
                <span className={`mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full ${
                  occurrence.state === "due" ? "bg-emerald-400" : occurrence.state === "missed" ? "bg-amber-400" : "bg-zinc-600"
                }`} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-zinc-100">{occurrence.routine.title}</p>
                    <span className="rounded border border-zinc-700 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-zinc-500">{occurrence.state}</span>
                  </div>
                  <p className="mt-1 text-xs text-zinc-400">{formatOccurrenceTime(occurrence)}</p>
                  <p className={`mt-1 text-xs ${adjusted ? "text-amber-300" : "text-zinc-600"}`}>
                    {timeResolutionMessage(occurrence.time_resolution)}
                  </p>
                </div>
              </div>
              {actionable && (
                <div className="flex flex-wrap justify-end gap-2 border-t border-zinc-800 pt-3">
                  <Button variant="ghost" size="sm" disabled={workingId === occurrence.id} onClick={() => void skip(occurrence)}>Skip</Button>
                  {occurrence.routine.mode === "defined" ? (
                    <Button size="sm" disabled={!onLogMeal} onClick={() => log(occurrence)}>
                      <Utensils className="h-3.5 w-3.5" /> Log meal
                    </Button>
                  ) : (
                    <Button size="sm" disabled={!onUseRoughRoutine} onClick={() => log(occurrence)}>Open rough plan</Button>
                  )}
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </section>
  );
}

function SchedulePanel({ routine, timezone }: { routine: Routine; timezone: string }) {
  const qc = useQueryClient();
  const mutations = useRef(new Map<string, StableMutation>());
  const schedules = useQuery({
    queryKey: ["routine-schedules", routine.id],
    queryFn: () => listSchedules(routine.id),
  });
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState<Omit<ScheduleCreate, "client_mutation_id">>(() => ({
    local_time: "12:00",
    timezone,
    frequency: "daily",
    interval: 1,
    iso_weekdays: [],
    start_date: localDate(),
    end_date: null,
    reminder_minutes: null,
  }));

  const create = useMutation({
    mutationFn: async () => {
      const validation = validateSchedule(input);
      if (validation) throw new Error(validation);
      return createSchedule(routine.id, input, mutationFor(mutations, "create", input));
    },
    onSuccess: async () => {
      mutations.current.delete("create");
      setOpen(false);
      setError(null);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["routine-schedules", routine.id] }),
        qc.invalidateQueries({ queryKey: ["agenda"] }),
      ]);
    },
    onError: (reason) => setError(errorMessage(reason)),
  });

  const toggle = async (schedule: Schedule) => {
    const value = { id: schedule.id, version: schedule.version, enabled: !schedule.enabled };
    setError(null);
    try {
      await setScheduleEnabled(schedule, !schedule.enabled, mutationFor(mutations, `toggle:${schedule.id}`, value));
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["routine-schedules", routine.id] }),
        qc.invalidateQueries({ queryKey: ["agenda"] }),
      ]);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  };

  const toggleWeekday = (day: number) => setInput((current) => ({
    ...current,
    iso_weekdays: current.iso_weekdays.includes(day)
      ? current.iso_weekdays.filter((item) => item !== day)
      : [...current.iso_weekdays, day].sort(),
  }));

  return (
    <div className="space-y-3 border-t border-zinc-800 pt-3">
      <div className="flex items-center justify-between">
        <p className={eyebrow}>Schedules</p>
        <Button variant="ghost" size="sm" onClick={() => setOpen((value) => !value)}>
          <Plus className="h-3.5 w-3.5" /> Add
        </Button>
      </div>
      {schedules.data?.map((schedule) => (
        <div key={schedule.id} className="flex items-center gap-3 rounded-lg bg-zinc-950/60 p-3">
          <CalendarClock className="h-4 w-4 text-zinc-500" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium text-zinc-300">
              {schedule.local_time.slice(0, 5)} · every {schedule.interval > 1 ? `${schedule.interval} ` : ""}{schedule.frequency === "daily" ? "day(s)" : "week(s)"}
            </p>
            <p className="truncate text-[11px] text-zinc-600">
              {schedule.frequency === "weekly" ? schedule.iso_weekdays.map((day) => WEEKDAYS[day - 1][1]).join(", ") : "Daily"} · {schedule.timezone}
            </p>
            <p className="truncate text-[11px] text-zinc-600">
              {schedule.start_date}{schedule.end_date ? ` to ${schedule.end_date}` : " onward"}
              {schedule.reminder_minutes !== null ? ` · reminder ${schedule.reminder_minutes} min before` : " · no reminder"}
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => void toggle(schedule)}>{schedule.enabled ? "Disable" : "Enable"}</Button>
        </div>
      ))}
      {open && (
        <div className="grid gap-3 rounded-xl border border-zinc-800 bg-zinc-950/40 p-3 sm:grid-cols-2">
          <label className="space-y-1"><span className={eyebrow}>Local time</span><input type="time" className={field} value={input.local_time} onChange={(event) => setInput({ ...input, local_time: event.target.value })} /></label>
          <label className="space-y-1"><span className={eyebrow}>Timezone</span><input className={field} value={input.timezone} onChange={(event) => setInput({ ...input, timezone: event.target.value })} /></label>
          <label className="space-y-1"><span className={eyebrow}>Frequency</span><select className={field} value={input.frequency} onChange={(event) => setInput({ ...input, frequency: event.target.value as "daily" | "weekly", iso_weekdays: [] })}><option value="daily">Daily</option><option value="weekly">Weekly</option></select></label>
          <label className="space-y-1"><span className={eyebrow}>Every (1-4)</span><input type="number" min={1} max={4} className={field} value={input.interval} onChange={(event) => setInput({ ...input, interval: Number(event.target.value) })} /></label>
          {input.frequency === "weekly" && (
            <fieldset className="space-y-2 sm:col-span-2"><legend className={eyebrow}>Weekdays</legend><div className="flex flex-wrap gap-1.5">{WEEKDAYS.map(([day, label]) => <button type="button" key={day} onClick={() => toggleWeekday(day)} className={`rounded-lg border px-2.5 py-1.5 text-xs ${input.iso_weekdays.includes(day) ? "border-emerald-600/60 bg-emerald-950/40 text-emerald-300" : "border-zinc-700 text-zinc-500"}`}>{label}</button>)}</div></fieldset>
          )}
          <label className="space-y-1"><span className={eyebrow}>Starts</span><input type="date" className={field} value={input.start_date} onChange={(event) => setInput({ ...input, start_date: event.target.value })} /></label>
          <label className="space-y-1"><span className={eyebrow}>Ends (optional)</span><input type="date" className={field} value={input.end_date ?? ""} onChange={(event) => setInput({ ...input, end_date: event.target.value || null })} /></label>
          <label className="space-y-1 sm:col-span-2"><span className={eyebrow}>Reminder minutes (optional)</span><input type="number" min={0} max={1440} className={field} value={input.reminder_minutes ?? ""} onChange={(event) => setInput({ ...input, reminder_minutes: event.target.value === "" ? null : Number(event.target.value) })} /></label>
          {error && <p className="text-xs text-red-400 sm:col-span-2">{error}</p>}
          <div className="flex justify-end gap-2 sm:col-span-2"><Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button><Button size="sm" disabled={create.isPending} onClick={() => create.mutate()}>{create.isPending ? "Creating..." : "Create schedule"}</Button></div>
        </div>
      )}
      {!open && error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}

function RoutineEditor({ routine, timezone, onClose }: { routine: Routine | null; timezone: string; onClose: () => void }) {
  const qc = useQueryClient();
  const mutations = useRef(new Map<string, StableMutation>());
  const [draft, setDraft] = useState<RoutineDraft>(() => routine ? {
    title: routine.title,
    mode: routine.mode,
    roughText: routine.rough_text ?? "",
    items: routine.items.map((item) => ({ product: item.product, quantityG: item.quantity_g })),
  } : emptyDraft());
  const [productQuery, setProductQuery] = useState("");
  const deferredQuery = useDeferredValue(productQuery);
  const [selectedProductId, setSelectedProductId] = useState("");
  const [quantity, setQuantity] = useState("100");
  const [error, setError] = useState<string | null>(null);
  const products = useQuery({
    queryKey: ["routine-products", deferredQuery],
    queryFn: () => listProducts(deferredQuery),
    enabled: draft.mode === "defined",
  });

  const save = useMutation({
    mutationFn: async () => {
      const validation = validateRoutineDraft(draft);
      if (validation) throw new Error(validation);
      const value = { draft, id: routine?.id ?? null, version: routine?.version ?? null };
      return saveRoutine(draft, mutationFor(mutations, "save", value), routine ?? undefined);
    },
    onSuccess: async () => {
      setError(null);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["routines"] }),
        qc.invalidateQueries({ queryKey: ["agenda"] }),
      ]);
      onClose();
    },
    onError: (reason) => setError(errorMessage(reason)),
  });

  const addProduct = () => {
    const product = products.data?.find((item) => item.id === selectedProductId);
    const quantityG = Number(quantity.replace(",", "."));
    if (!product || !Number.isFinite(quantityG)) return;
    setDraft((current) => ({ ...current, items: [...current.items.filter((item) => item.product.id !== product.id), { product, quantityG }] }));
    setSelectedProductId("");
  };

  return (
    <Card className="space-y-4 border-emerald-900/50 bg-zinc-900/80">
      <div className="flex items-center justify-between"><div><p className={eyebrow}>{routine ? "Edit routine" : "New routine"}</p><h2 className="mt-1 font-semibold">{routine?.title ?? "Build a reusable meal plan"}</h2></div><Button variant="ghost" size="icon" onClick={onClose} aria-label="Close editor"><X className="h-4 w-4" /></Button></div>
      <label className="space-y-1"><span className={eyebrow}>Title</span><input className={field} maxLength={100} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} placeholder="Weekday breakfast" /></label>
      <div className="grid grid-cols-2 gap-2">{(["rough", "defined"] as const).map((mode) => <button type="button" key={mode} onClick={() => setDraft({ ...draft, mode })} className={`rounded-lg border p-3 text-left ${draft.mode === mode ? "border-emerald-600/60 bg-emerald-950/30 text-emerald-200" : "border-zinc-700 text-zinc-500"}`}><span className="block text-sm font-medium capitalize">{mode}</span><span className="mt-1 block text-[11px]">{mode === "rough" ? "Flexible text for the coach" : "Accepted products and amounts"}</span></button>)}</div>
      {draft.mode === "rough" ? (
        <label className="space-y-1"><span className={eyebrow}>Meal idea</span><textarea className={`${field} min-h-28 resize-y`} maxLength={2000} value={draft.roughText} onChange={(event) => setDraft({ ...draft, roughText: event.target.value })} placeholder="Something light with fish, vegetables, and rice..." /></label>
      ) : (
        <div className="space-y-3">
          <label className="relative block"><Search className="absolute left-3 top-2.5 h-4 w-4 text-zinc-600" /><input type="search" className={`${field} pl-9`} value={productQuery} onChange={(event) => setProductQuery(event.target.value)} placeholder="Search accepted products" /></label>
          <div className="grid grid-cols-[1fr_6rem_auto] gap-2"><select className={field} value={selectedProductId} onChange={(event) => setSelectedProductId(event.target.value)}><option value="">Select product</option>{products.data?.filter((product) => !draft.items.some((item) => item.product.id === product.id)).map((product) => <option key={product.id} value={product.id}>{product.brand ? `${product.brand} ` : ""}{product.name}</option>)}</select><input className={field} inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} aria-label="Quantity in grams" /><Button variant="outline" onClick={addProduct} disabled={!selectedProductId}>Add</Button></div>
          <div className="space-y-2">{draft.items.map((item) => <div key={item.product.id} className="flex items-center gap-2 rounded-lg bg-zinc-950/60 p-2.5"><div className="min-w-0 flex-1"><p className="truncate text-sm text-zinc-200">{item.product.brand ? `${item.product.brand} ` : ""}{item.product.name}</p><p className="text-[11px] text-zinc-600">Accepted product</p></div><input className={`${field} w-24`} inputMode="decimal" value={item.quantityG} onChange={(event) => setDraft((current) => ({ ...current, items: current.items.map((entry) => entry.product.id === item.product.id ? { ...entry, quantityG: Number(event.target.value) } : entry) }))} aria-label={`Quantity for ${item.product.name}`} /><span className="text-xs text-zinc-600">g</span><Button variant="ghost" size="icon" onClick={() => setDraft((current) => ({ ...current, items: current.items.filter((entry) => entry.product.id !== item.product.id) }))} aria-label={`Remove ${item.product.name}`}><X className="h-4 w-4" /></Button></div>)}</div>
        </div>
      )}
      {error && <p className="text-xs text-red-400">{error}</p>}
      <div className="flex justify-end gap-2 border-t border-zinc-800 pt-3"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={save.isPending} onClick={() => save.mutate()}><Check className="h-4 w-4" />{save.isPending ? "Saving..." : "Save routine"}</Button></div>
      {routine && <SchedulePanel routine={routine} timezone={timezone} />}
    </Card>
  );
}

export function Routines({ timezone = defaultTimezone(), onLogMeal, onUseRoughRoutine }: RoutinesProps) {
  const qc = useQueryClient();
  const mutations = useRef(new Map<string, StableMutation>());
  const routines = useQuery({ queryKey: ["routines"], queryFn: () => listRoutines(false) });
  const [editor, setEditor] = useState<Routine | "new" | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const archive = async (routine: Routine) => {
    if (!window.confirm(`Archive “${routine.title}” and disable its schedules?`)) return;
    const value = { id: routine.id, version: routine.version };
    setError(null);
    try {
      await archiveRoutine(routine, mutationFor(mutations, `archive:${routine.id}`, value));
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["routines"] }),
        qc.invalidateQueries({ queryKey: ["agenda"] }),
      ]);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  };

  return (
    <div className="mx-auto grid max-w-6xl gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(22rem,.95fr)]">
      <AgendaPanel onLogMeal={onLogMeal} onUseRoughRoutine={onUseRoughRoutine} />
      <section className="space-y-3" aria-labelledby="routines-heading">
        <div className="flex items-end justify-between">
          <div><h2 id="routines-heading" className="text-base font-semibold">Meal routines</h2><p className="mt-1 text-xs text-zinc-500">Reusable plans stay separate from confirmed intake.</p></div>
          <Button size="sm" onClick={() => setEditor("new")}><Plus className="h-3.5 w-3.5" /> New routine</Button>
        </div>
        {error && <p className="text-xs text-red-400">{error}</p>}
        {editor && <RoutineEditor key={editor === "new" ? "new" : `${editor.id}:${editor.version}`} routine={editor === "new" ? null : editor} timezone={timezone} onClose={() => setEditor(null)} />}
        {routines.isLoading && <div className="h-32 animate-pulse rounded-xl bg-zinc-900" />}
        {routines.error && <p className="rounded-xl border border-red-900/50 p-3 text-sm text-red-300">{errorMessage(routines.error)}</p>}
        <div className="space-y-2">
          {routines.data?.map((routine) => (
            <Card key={routine.id} className="space-y-3">
              <button type="button" className="flex w-full items-start gap-3 text-left" onClick={() => setExpanded(expanded === routine.id ? null : routine.id)}>
                <span className="rounded-lg border border-zinc-700 bg-zinc-950 p-2"><Utensils className="h-4 w-4 text-emerald-400" /></span>
                <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><p className="truncate text-sm font-medium text-zinc-100">{routine.title}</p><span className="rounded border border-zinc-700 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-zinc-500">{routine.mode}</span></div><p className="mt-1 truncate text-xs text-zinc-500">{routine.mode === "rough" ? routine.rough_text : `${routine.items.length} accepted product${routine.items.length === 1 ? "" : "s"}`}</p></div>
                <ChevronDown className={`mt-2 h-4 w-4 text-zinc-600 transition-transform ${expanded === routine.id ? "rotate-180" : ""}`} />
              </button>
              {expanded === routine.id && (
                <div className="space-y-3 border-t border-zinc-800 pt-3">
                  {routine.mode === "defined" && <ul className="space-y-1">{routine.items.map((item) => <li key={item.product.id} className="flex justify-between text-xs"><span className="text-zinc-400">{item.product.brand ? `${item.product.brand} ` : ""}{item.product.name}</span><span className="tabular-nums text-zinc-600">{item.quantity_g} g</span></li>)}</ul>}
                  <div className="flex justify-end gap-2"><Button variant="ghost" size="sm" onClick={() => setEditor(routine)}><Edit3 className="h-3.5 w-3.5" /> Edit</Button><Button variant="ghost" size="sm" className="text-red-300" onClick={() => void archive(routine)}><Archive className="h-3.5 w-3.5" /> Archive</Button></div>
                  <SchedulePanel routine={routine} timezone={timezone} />
                </div>
              )}
            </Card>
          ))}
          {routines.data?.length === 0 && <Card className="py-8 text-center text-sm text-zinc-500">Create a rough idea or a precise product-based routine.</Card>}
        </div>
      </section>
    </div>
  );
}

export default Routines;
