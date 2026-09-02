import { lazy, Suspense, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Plus, Sparkles } from "lucide-react";
import { ApiError, api } from "./lib/api";
import type { DailySummary, MealLog, MeInfo } from "./lib/types";
import {
  discardOccurrenceCompletionAttempt,
  discardPendingMealLog,
  flushOccurrenceCompletionAttempts,
  flushPendingMealLogs,
  getMealLogQueueState,
  getOccurrenceCompletionState,
  MEAL_LOG_QUEUE_CHANGED_EVENT,
  type OccurrenceCompletionAttempt,
  type PendingMealLog,
} from "./lib/offline/db";
import { TargetBars } from "./components/TargetBars";
import { MealList } from "./components/MealList";
import { Assistant } from "./components/Assistant";
import { ManualEntry } from "./components/ManualEntry";
import { BottomNav, type Tab } from "./components/BottomNav";
import { DesktopHeader } from "./components/DesktopHeader";
import { Button } from "./components/ui/button";
import { Card } from "./components/ui/card";
import type { AnalyticsIntent, AssistantLaunch, AssistantMode } from "./lib/assistant";
import { formatCountdown, useAgenda, type RoutineMealProposal } from "./lib/routines";
import { ProposalCard } from "./components/ProposalCard";
import { revokeWebPushForLogout } from "./lib/push";

// Code-split: keeps ZXing (camera pipeline), Recharts (charts) and the admin
// settings surface out of the initial bundle — all load on demand.
const ScanSheet = lazy(() => import("./components/ScanSheet").then((m) => ({ default: m.ScanSheet })));
const Analytics = lazy(() => import("./components/Analytics").then((m) => ({ default: m.Analytics })));
const SettingsView = lazy(() => import("./components/Settings").then((m) => ({ default: m.SettingsView })));
const Routines = lazy(() => import("./components/Routines"));

function LoginGate() {
  const qc = useQueryClient();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: username.trim(), password }),
      });
      qc.clear();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <Card className="w-full max-w-xs space-y-4">
        <div className="flex items-center gap-2.5">
          <img src="/logo.svg" alt="" className="h-8 w-8" />
          <h1 className="text-lg font-semibold">PlateOS</h1>
        </div>
        <input
          className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void submit()}
          autoComplete="current-password"
          className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
        />
        {error && <p className="text-xs text-red-400">{error}</p>}
        <Button className="w-full" onClick={() => void submit()}>
          Sign in
        </Button>
      </Card>
    </div>
  );
}

const PAGE_TITLES: Record<Tab, string> = {
  today: "Today",
  scan: "Scan",
  plan: "Plan",
  coach: "Coach",
  stats: "Stats",
  settings: "Settings",
};

const PAGE_DESCRIPTIONS: Record<Tab, string> = {
  today: "Your intake, targets, and confirmed meals for the day.",
  scan: "Capture a barcode or nutrition label and review before logging.",
  plan: "Build reusable meals, schedule them, and review upcoming occurrences.",
  coach: "Describe a meal naturally, then verify the coach's proposal.",
  stats: "Review recent intake patterns against your current targets.",
  settings: "Manage your account, household, and connected providers.",
};

const TEXT_EYEBROW = "text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-500";

export default function App() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>(() => window.location.pathname === "/plan" ? "plan" : "today");
  const [showManual, setShowManual] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);
  const [queuedCount, setQueuedCount] = useState(0);
  const [failedQueue, setFailedQueue] = useState<PendingMealLog[]>([]);
  const [pendingOccurrences, setPendingOccurrences] = useState(0);
  const [failedOccurrences, setFailedOccurrences] = useState<OccurrenceCompletionAttempt[]>([]);
  const [assistantLaunch, setAssistantLaunch] = useState<AssistantLaunch | null>(null);
  const [analyticsIntent, setAnalyticsIntent] = useState<AnalyticsIntent | null>(null);
  const [routineProposal, setRoutineProposal] = useState<RoutineMealProposal | null>(null);

  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<MeInfo>("/api/auth/me"),
    retry: false,
  });

  const logout = useMutation({
    mutationFn: async () => {
      if (me.data?.id) await revokeWebPushForLogout(me.data.id);
      return api("/api/auth/logout", { method: "POST" });
    },
    onSuccess: () => qc.clear(),
  });

  const summary = useQuery({
    queryKey: ["daily-summary"],
    queryFn: () => api<DailySummary>("/api/daily-summary"),
    retry: false,
  });

  const logs = useQuery({
    queryKey: ["meal-logs"],
    queryFn: () => api<MealLog[]>("/api/meal-logs"),
    retry: false,
  });
  const agenda = useAgenda({ days: 7 });

  // Offline queue: flush on mount and whenever connectivity returns.
  useEffect(() => {
    const accountId = me.data?.id;
    if (!accountId) {
      setQueuedCount(0);
      setFailedQueue([]);
      setPendingOccurrences(0);
      setFailedOccurrences([]);
      return;
    }
    let active = true;
    const refreshQueue = () => {
      void Promise.all([
        getMealLogQueueState(accountId),
        getOccurrenceCompletionState(accountId),
      ]).then(([mealState, occurrenceState]) => {
        if (!active) return;
        setQueuedCount(mealState.pending);
        setFailedQueue(mealState.failed);
        setPendingOccurrences(occurrenceState.pending);
        setFailedOccurrences(occurrenceState.failed);
      });
    };
    const flush = () => {
      void Promise.all([
        flushPendingMealLogs(accountId),
        flushOccurrenceCompletionAttempts(accountId),
      ]).then(([mealCount, occurrenceCount]) => {
        if (!active) return;
        if (mealCount + occurrenceCount > 0) void qc.invalidateQueries();
        refreshQueue();
      });
    };
    const goOnline = () => {
      setOnline(true);
      flush();
    };
    const goOffline = () => setOnline(false);
    const onVisible = () => {
      if (document.visibilityState === "visible" && navigator.onLine) flush();
    };
    flush();
    refreshQueue();
    const retryTimer = window.setInterval(() => {
      if (navigator.onLine) flush();
    }, 30_000);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    window.addEventListener(MEAL_LOG_QUEUE_CHANGED_EVENT, refreshQueue);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      active = false;
      window.clearInterval(retryTimer);
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
      window.removeEventListener(MEAL_LOG_QUEUE_CHANGED_EVENT, refreshQueue);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [me.data?.id, qc]);

  const deleteLog = async (id: string) => {
    await api(`/api/meal-logs/${id}`, { method: "DELETE" });
    await qc.invalidateQueries();
  };

  const launchAssistant = (
    prompt: string,
    mode: AssistantMode,
    surface: AssistantLaunch["surface"],
    analytics?: Omit<AnalyticsIntent, "id">,
  ) => {
    setAssistantLaunch({ id: crypto.randomUUID(), prompt, mode, surface, analytics });
    setTab("coach");
  };

  const openAnalytics = (intent: AnalyticsIntent) => {
    setAnalyticsIntent(intent);
    setTab("stats");
  };

  if (summary.error instanceof ApiError && summary.error.status === 401) return <LoginGate />;

  const statusLine =
    failedQueue.length + failedOccurrences.length > 0 ? (
      <span className="text-xs text-red-400">
        {`${failedQueue.length + failedOccurrences.length} queued action${failedQueue.length + failedOccurrences.length === 1 ? "" : "s"} need attention`}
      </span>
    ) : queuedCount + pendingOccurrences > 0 ? (
      <span className="text-xs text-amber-500">{`${queuedCount + pendingOccurrences} action${queuedCount + pendingOccurrences === 1 ? "" : "s"} queued`}</span>
    ) : !online ? (
      <span className="text-xs text-amber-500">offline - logging will queue</span>
    ) : agenda.data?.countdown_seconds !== null && agenda.data?.countdown_seconds !== undefined ? (
      <button type="button" className="text-xs text-emerald-400" onClick={() => setTab("plan")}>
        Next meal {formatCountdown(agenda.data.countdown_seconds)}
      </button>
    ) : null;

  return (
    <div className="min-h-full bg-zinc-950">
      <DesktopHeader
        tab={tab}
        onTab={setTab}
        me={me.data}
        onLogout={() => logout.mutate()}
        status={statusLine}
      />

      <div className="mx-auto flex min-h-full max-w-7xl flex-col px-4 pb-24 pt-[env(safe-area-inset-top)] md:min-h-[calc(100vh-76px)] md:px-6 md:pb-12 md:pt-9 lg:px-10">
        {/* Mobile header */}
        <header className="space-y-3 py-4 md:hidden">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-semibold tracking-tight">PlateOS</h1>
            {statusLine}
          </div>
          <TargetBars summary={summary.data} />
        </header>

        {/* Desktop page heading */}
        <div className="hidden justify-between border-b border-zinc-800/70 pb-6 md:flex">
          <div>
            <p className="mb-1 text-[10px] font-medium uppercase tracking-[0.16em] text-emerald-500/80">
              Workspace
            </p>
            <h1 className="text-2xl font-semibold tracking-[-0.025em] text-zinc-100">{PAGE_TITLES[tab]}</h1>
            <p className="mt-1 text-sm text-zinc-500">{PAGE_DESCRIPTIONS[tab]}</p>
          </div>
          <div className="pt-2 xl:hidden">{statusLine}</div>
        </div>

        {failedQueue.length > 0 && (
          <Card className="mb-4 space-y-2 border-red-900/60">
            <h2 className="text-sm font-semibold text-red-300">Queued logs needing attention</h2>
            {failedQueue.map((item) => (
              <div key={item.id} className="flex items-start justify-between gap-3 text-xs">
                <div>
                  <p className="text-zinc-200">{item.payload.custom_name ?? "Meal log"}</p>
                  <p className="text-zinc-500">{item.lastError ?? "The server rejected this log."}</p>
                </div>
                {item.id !== undefined && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void discardPendingMealLog(me.data!.id, item.id!)}
                  >
                    Discard
                  </Button>
                )}
              </div>
            ))}
          </Card>
        )}

        {failedOccurrences.length > 0 && (
          <Card className="mb-4 space-y-2 border-red-900/60">
            <h2 className="text-sm font-semibold text-red-300">Planned meals needing attention</h2>
            {failedOccurrences.map((attempt) => (
              <div key={attempt.id} className="flex items-start justify-between gap-3 text-xs">
                <div>
                  <p className="text-zinc-200">Occurrence completion</p>
                  <p className="text-zinc-500">{attempt.lastError ?? "The server rejected this action."}</p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void discardOccurrenceCompletionAttempt(me.data!.id, attempt.id)}
                >
                  Discard
                </Button>
              </div>
            ))}
          </Card>
        )}

        <main className="flex-1 space-y-4 md:pt-7">
          {tab === "today" && (
            <section className="space-y-2 lg:grid lg:grid-cols-[minmax(0,1fr)_360px] lg:items-start lg:gap-10 lg:space-y-0">
              <div className="space-y-2">
                {agenda.data?.occurrences[0] && (
                  <button
                    type="button"
                    onClick={() => setTab("plan")}
                    className="flex w-full items-center gap-3 rounded-xl border border-emerald-950 bg-emerald-950/10 p-3 text-left"
                  >
                    <CalendarClock className="h-4 w-4 text-emerald-400" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-500">Next planned meal</span>
                      <span className="block truncate text-sm text-zinc-200">{agenda.data.occurrences[0].routine.title}</span>
                    </span>
                    <span className="text-xs text-emerald-400">{formatCountdown(agenda.data.countdown_seconds)}</span>
                  </button>
                )}
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-medium text-zinc-400 md:hidden lg:block">Today's logs</h2>
                  <div className="flex gap-2">
                    <Button variant="ghost" size="sm" onClick={() => launchAssistant("Help me plan the rest of today based on what I have logged and what remains.", "coach", "today")}>
                      <Sparkles className="h-3 w-3" /> Plan with AI
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setShowManual((v) => !v)}>
                      <Plus className="h-3 w-3" /> Quick log
                    </Button>
                  </div>
                </div>
                {showManual && (
                  <Card>
                    <ManualEntry
                      onDone={() => {
                        setShowManual(false);
                        void qc.invalidateQueries();
                      }}
                    />
                  </Card>
                )}
                <MealList logs={logs.data} onDelete={(id) => void deleteLog(id)} />
              </div>
              <Card className="hidden space-y-3 lg:sticky lg:top-[105px] lg:block">
                <h3 className={TEXT_EYEBROW}>Budget</h3>
                <TargetBars summary={summary.data} />
              </Card>
            </section>
          )}
          {tab === "scan" && (
            <Suspense fallback={<div className="h-64 animate-pulse rounded-xl bg-zinc-900" />}>
              <ScanSheet onClose={() => setTab("today")} />
            </Suspense>
          )}
          {tab === "plan" && (
            <Suspense fallback={<div className="h-64 animate-pulse rounded-xl bg-zinc-900" />}>
              <div className="space-y-4">
                {routineProposal && (
                  <ProposalCard
                    items={routineProposal.items}
                    durableOccurrenceId={routineProposal.occurrence.id}
                    onDone={() => setRoutineProposal(null)}
                  />
                )}
                <Routines
                  timezone={summary.data?.timezone}
                  onLogMeal={setRoutineProposal}
                  onUseRoughRoutine={(routine) => launchAssistant(
                    `Turn this rough meal routine into a concrete proposal for today: ${routine.title}. ${routine.rough_text ?? ""}`,
                    "coach",
                    "today",
                  )}
                />
              </div>
            </Suspense>
          )}
          <div className={tab === "coach" ? "block" : "hidden"}>
            <Assistant launch={assistantLaunch} onOpenAnalytics={openAnalytics} />
          </div>
          {tab === "stats" && (
            <Suspense fallback={<div className="h-64 animate-pulse rounded-xl bg-zinc-900" />}>
              <Analytics
                intent={analyticsIntent}
                onAskCoach={(view) => launchAssistant(
                  "Analyze the current statistics view. Explain the most useful pattern, any data-quality limitation, and suggest one next action.",
                  "analytics",
                  "stats",
                  view,
                )}
              />
            </Suspense>
          )}
          {tab === "settings" && (
            <Suspense fallback={<div className="h-64 animate-pulse rounded-xl bg-zinc-900" />}>
              <SettingsView />
            </Suspense>
          )}
        </main>
      </div>

      <BottomNav tab={tab} onTab={setTab} />
    </div>
  );
}
