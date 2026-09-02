import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Check, X } from "lucide-react";
import type { AssistantMealPlanDraft } from "../lib/assistant";
import {
  createSchedule,
  routineFingerprint,
  saveRoutine,
  stableRoutineMutation,
  validateRoutineDraft,
  validateSchedule,
} from "../lib/routines";
import type { Routine, RoutineDraft, ScheduleCreate } from "../lib/routines";
import { Button } from "./ui/button";

const field = "w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-200 outline-none focus:border-emerald-600";
const label = "text-[10px] font-medium uppercase tracking-wider text-zinc-500";
const weekdays = [[1, "Mon"], [2, "Tue"], [3, "Wed"], [4, "Thu"], [5, "Fri"], [6, "Sat"], [7, "Sun"]] as const;

type ScheduleInput = Omit<ScheduleCreate, "client_mutation_id">;
type StableId = ReturnType<typeof stableRoutineMutation>;

function localDate(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

function defaultSchedule(): ScheduleInput {
  return {
    local_time: "12:00",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    frequency: "daily",
    interval: 1,
    iso_weekdays: [],
    start_date: localDate(),
    end_date: null,
    reminder_minutes: null,
  };
}

export function MealPlanReview({ draft: proposed, onDone }: { draft: AssistantMealPlanDraft; onDone: () => void }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<RoutineDraft>({
    title: proposed.title,
    mode: "rough",
    roughText: proposed.rough_text,
    items: [],
  });
  const [includeSchedule, setIncludeSchedule] = useState(proposed.schedule !== null);
  const [schedule, setSchedule] = useState<ScheduleInput>(proposed.schedule ?? defaultSchedule);
  const [savedRoutine, setSavedRoutine] = useState<Routine | null>(null);
  const [saving, setSaving] = useState(false);
  const [complete, setComplete] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const routineMutation = useRef<StableId | null>(null);
  const scheduleMutation = useRef<StableId | null>(null);

  const toggleWeekday = (day: number) => setSchedule((current) => ({
    ...current,
    iso_weekdays: current.iso_weekdays.includes(day)
      ? current.iso_weekdays.filter((value) => value !== day)
      : [...current.iso_weekdays, day].sort(),
  }));

  const confirm = async () => {
    if (!navigator.onLine) {
      setStatus("Reconnect before creating this routine. Assistant drafts are not queued.");
      return;
    }
    const routineError = savedRoutine ? null : validateRoutineDraft(draft);
    const scheduleError = includeSchedule ? validateSchedule(schedule) : null;
    if (routineError || scheduleError) {
      setStatus(routineError ?? scheduleError);
      return;
    }

    setSaving(true);
    setStatus(null);
    let routine = savedRoutine;
    try {
      if (!routine) {
        routineMutation.current = stableRoutineMutation(
          routineMutation.current,
          routineFingerprint({ draft }),
        );
        routine = await saveRoutine(draft, routineMutation.current.id);
        setSavedRoutine(routine);
      }

      if (includeSchedule) {
        scheduleMutation.current = stableRoutineMutation(
          scheduleMutation.current,
          routineFingerprint({ routineId: routine.id, schedule }),
        );
        try {
          await createSchedule(routine.id, schedule, scheduleMutation.current.id);
        } catch (reason) {
          await qc.invalidateQueries({ queryKey: ["routines"] });
          setStatus(`Routine saved, but the schedule was not created: ${reason instanceof Error ? reason.message : String(reason)}`);
          return;
        }
      }

      await Promise.all([
        qc.invalidateQueries({ queryKey: ["routines"] }),
        qc.invalidateQueries({ queryKey: ["agenda"] }),
      ]);
      setComplete(true);
      setStatus(includeSchedule ? "Routine and schedule created." : "Routine created.");
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="space-y-4 rounded-xl border border-sky-900/60 bg-sky-950/10 p-4" aria-label="Review meal plan draft">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2"><CalendarClock className="h-4 w-4 text-sky-400" /><h3 className="text-sm font-semibold text-zinc-100">Review meal plan</h3></div>
          <p className="mt-1 text-xs text-sky-300/70">Draft only. Nothing is created until you confirm.</p>
        </div>
        <Button variant="ghost" size="icon" onClick={onDone} aria-label="Dismiss meal plan draft"><X className="h-4 w-4" /></Button>
      </div>

      <label className="space-y-1"><span className={label}>Routine title</span><input className={field} maxLength={100} disabled={savedRoutine !== null} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></label>
      <label className="space-y-1"><span className={label}>Flexible meal plan</span><textarea className={`${field} min-h-28 resize-y`} maxLength={2000} disabled={savedRoutine !== null} value={draft.roughText} onChange={(event) => setDraft({ ...draft, roughText: event.target.value })} /></label>
      <p className="text-xs text-zinc-500">This creates a rough routine only. It does not accept products or create meal logs.</p>

      <label className="flex items-center gap-2 text-sm text-zinc-300">
        <input type="checkbox" checked={includeSchedule} disabled={savedRoutine !== null && complete} onChange={(event) => setIncludeSchedule(event.target.checked)} />
        Also create a schedule after the routine is saved
      </label>
      {includeSchedule && (
        <div className="grid gap-3 rounded-xl border border-zinc-800 bg-zinc-950/40 p-3 sm:grid-cols-2">
          <label className="space-y-1"><span className={label}>Local time</span><input type="time" className={field} disabled={complete} value={schedule.local_time.slice(0, 5)} onChange={(event) => setSchedule({ ...schedule, local_time: event.target.value })} /></label>
          <label className="space-y-1"><span className={label}>Timezone</span><input className={field} maxLength={64} disabled={complete} value={schedule.timezone} onChange={(event) => setSchedule({ ...schedule, timezone: event.target.value })} /></label>
          <label className="space-y-1"><span className={label}>Frequency</span><select className={field} disabled={complete} value={schedule.frequency} onChange={(event) => setSchedule({ ...schedule, frequency: event.target.value as "daily" | "weekly", iso_weekdays: [] })}><option value="daily">Daily</option><option value="weekly">Weekly</option></select></label>
          <label className="space-y-1"><span className={label}>Every (1-4)</span><input type="number" min={1} max={4} className={field} disabled={complete} value={schedule.interval} onChange={(event) => setSchedule({ ...schedule, interval: Number(event.target.value) })} /></label>
          {schedule.frequency === "weekly" && <fieldset className="space-y-2 sm:col-span-2"><legend className={label}>Weekdays</legend><div className="flex flex-wrap gap-1.5">{weekdays.map(([day, name]) => <button type="button" key={day} disabled={complete} onClick={() => toggleWeekday(day)} className={`rounded-lg border px-2.5 py-1.5 text-xs ${schedule.iso_weekdays.includes(day) ? "border-sky-600/60 bg-sky-950/40 text-sky-300" : "border-zinc-700 text-zinc-500"}`}>{name}</button>)}</div></fieldset>}
          <label className="space-y-1"><span className={label}>Starts</span><input type="date" className={field} disabled={complete} value={schedule.start_date} onChange={(event) => setSchedule({ ...schedule, start_date: event.target.value })} /></label>
          <label className="space-y-1"><span className={label}>Ends (optional)</span><input type="date" className={field} disabled={complete} value={schedule.end_date ?? ""} onChange={(event) => setSchedule({ ...schedule, end_date: event.target.value || null })} /></label>
          <label className="space-y-1 sm:col-span-2"><span className={label}>Reminder minutes (optional)</span><input type="number" min={0} max={1440} className={field} disabled={complete} value={schedule.reminder_minutes ?? ""} onChange={(event) => setSchedule({ ...schedule, reminder_minutes: event.target.value === "" ? null : Number(event.target.value) })} /></label>
        </div>
      )}

      {status && <p role="status" className={`text-xs ${complete ? "text-emerald-400" : savedRoutine ? "text-amber-300" : "text-red-400"}`}>{status}</p>}
      <div className="flex items-center justify-between gap-3 border-t border-zinc-800 pt-3">
        <p className="text-[11px] text-zinc-600">Creation requires an online connection and explicit confirmation.</p>
        {complete ? <Button variant="outline" onClick={onDone}>Close</Button> : <Button disabled={saving} onClick={() => void confirm()}><Check className="h-4 w-4" />{saving ? "Creating..." : savedRoutine && includeSchedule ? "Retry schedule" : savedRoutine ? "Finish without schedule" : includeSchedule ? "Create routine & schedule" : "Create routine"}</Button>}
      </div>
    </section>
  );
}
