import { lazy, Suspense, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { ApiError, api } from "./lib/api";
import type { DailySummary, MealLog, MeInfo } from "./lib/types";
import {
  discardPendingMealLog,
  flushPendingMealLogs,
  getMealLogQueueState,
  MEAL_LOG_QUEUE_CHANGED_EVENT,
  type PendingMealLog,
} from "./lib/offline/db";
import { TargetBars } from "./components/TargetBars";
import { MealList } from "./components/MealList";
import { Assistant } from "./components/Assistant";
import { ManualEntry } from "./components/ManualEntry";
import { BottomNav, type Tab } from "./components/BottomNav";
import { SideNav } from "./components/SideNav";
import { Button } from "./components/ui/button";
import { Card } from "./components/ui/card";

// Code-split: keeps ZXing (camera pipeline), Recharts (charts) and the admin
// settings surface out of the initial bundle — all load on demand.
const ScanSheet = lazy(() => import("./components/ScanSheet").then((m) => ({ default: m.ScanSheet })));
const Analytics = lazy(() => import("./components/Analytics").then((m) => ({ default: m.Analytics })));
const SettingsView = lazy(() => import("./components/Settings").then((m) => ({ default: m.SettingsView })));

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
      await flushPendingMealLogs();
      await qc.invalidateQueries();
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
  coach: "Coach",
  stats: "Stats",
  settings: "Settings",
};

const TEXT_EYEBROW = "text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-500";

export default function App() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("today");
  const [showManual, setShowManual] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);
  const [queuedCount, setQueuedCount] = useState(0);
  const [failedQueue, setFailedQueue] = useState<PendingMealLog[]>([]);

  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<MeInfo>("/api/auth/me"),
    retry: false,
  });

  const logout = useMutation({
    mutationFn: () => api("/api/auth/logout", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries(),
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

  // Offline queue: flush on mount and whenever connectivity returns.
  useEffect(() => {
    const refreshQueue = () => {
      void getMealLogQueueState().then((state) => {
        setQueuedCount(state.pending);
        setFailedQueue(state.failed);
      });
    };
    const flush = () => {
      void flushPendingMealLogs().then((n) => {
        if (n > 0) void qc.invalidateQueries();
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
      window.clearInterval(retryTimer);
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
      window.removeEventListener(MEAL_LOG_QUEUE_CHANGED_EVENT, refreshQueue);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [qc]);

  const deleteLog = async (id: string) => {
    await api(`/api/meal-logs/${id}`, { method: "DELETE" });
    await qc.invalidateQueries();
  };

  if (summary.error instanceof ApiError && summary.error.status === 401) return <LoginGate />;

  const statusLine =
    failedQueue.length > 0 ? (
      <span className={failedQueue.length ? "text-xs text-red-400" : "text-xs text-amber-500"}>
        {`${failedQueue.length} queued log${failedQueue.length === 1 ? "" : "s"} need attention`}
      </span>
    ) : queuedCount > 0 ? (
      <span className="text-xs text-amber-500">{`${queuedCount} log${queuedCount === 1 ? "" : "s"} queued`}</span>
    ) : !online ? (
      <span className="text-xs text-amber-500">offline - logging will queue</span>
    ) : null;

  return (
    <div className="flex min-h-full flex-col md:h-screen md:flex-row md:overflow-hidden">
      <SideNav tab={tab} onTab={setTab} me={me.data} onLogout={() => logout.mutate()} />

      <div className="flex min-h-full flex-1 flex-col px-4 pb-24 pt-safe md:mx-auto md:max-w-5xl md:px-10 md:pb-10 md:pt-8">
        {/* Mobile header */}
        <header className="space-y-3 py-4 md:hidden">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-semibold tracking-tight">PlateOS</h1>
            {statusLine}
          </div>
          <TargetBars summary={summary.data} />
        </header>

        {/* Desktop page heading */}
        <div className="hidden items-baseline justify-between pb-6 pt-2 md:flex">
          <h1 className="text-xl font-semibold tracking-tight">{PAGE_TITLES[tab]}</h1>
          {statusLine}
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
                  <Button variant="ghost" size="sm" onClick={() => void discardPendingMealLog(item.id!)}>
                    Discard
                  </Button>
                )}
              </div>
            ))}
          </Card>
        )}

        <main className="flex-1 space-y-4">
          {tab === "today" && (
            <section className="space-y-2 lg:grid lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start lg:gap-8 lg:space-y-0">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-medium text-zinc-400 md:hidden lg:block">Today's logs</h2>
                  <Button variant="outline" size="sm" onClick={() => setShowManual((v) => !v)}>
                    <Plus className="h-3 w-3" /> Quick log
                  </Button>
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
              <Card className="hidden space-y-3 lg:sticky lg:top-8 lg:block">
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
          {tab === "coach" && <Assistant />}
          {tab === "stats" && (
            <Suspense fallback={<div className="h-64 animate-pulse rounded-xl bg-zinc-900" />}>
              <Analytics />
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
