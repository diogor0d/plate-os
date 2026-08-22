import { lazy, Suspense, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { ApiError, api } from "./lib/api";
import type { DailySummary, MealLog } from "./lib/types";
import { flushPendingMealLogs } from "./lib/offline/db";
import { TargetBars } from "./components/TargetBars";
import { MealList } from "./components/MealList";
import { Assistant } from "./components/Assistant";
import { ManualEntry } from "./components/ManualEntry";
import { BottomNav, type Tab } from "./components/BottomNav";
import { Button } from "./components/ui/button";
import { Card } from "./components/ui/card";

// Code-split: keeps ZXing (camera pipeline) and Recharts (charts) out of the
// initial bundle — both tabs load on demand.
const ScanSheet = lazy(() => import("./components/ScanSheet").then((m) => ({ default: m.ScanSheet })));
const Analytics = lazy(() => import("./components/Analytics").then((m) => ({ default: m.Analytics })));

function LoginGate() {
  const qc = useQueryClient();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    try {
      await api("/api/auth/login", { method: "POST", body: JSON.stringify({ password }) });
      await qc.invalidateQueries();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <Card className="w-full max-w-xs space-y-4">
        <h1 className="text-lg font-semibold">PlateOS</h1>
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void submit()}
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

export default function App() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("today");
  const [showManual, setShowManual] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);

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
    const flush = () => {
      void flushPendingMealLogs().then((n) => {
        if (n > 0) void qc.invalidateQueries();
      });
    };
    const goOnline = () => {
      setOnline(true);
      flush();
    };
    const goOffline = () => setOnline(false);
    flush();
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, [qc]);

  const deleteLog = async (id: string) => {
    await api(`/api/meal-logs/${id}`, { method: "DELETE" });
    await qc.invalidateQueries();
  };

  if (summary.error instanceof ApiError && summary.error.status === 401) return <LoginGate />;

  return (
    <div className="mx-auto flex min-h-full max-w-md flex-col px-4 pt-safe">
      <header className="space-y-3 py-4">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold tracking-tight">PlateOS</h1>
          {!online && <span className="text-xs text-amber-500">offline — logging queued</span>}
        </div>
        <TargetBars summary={summary.data} />
      </header>

      <main className="flex-1 space-y-4 pb-24">
        {tab === "today" && (
          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium text-zinc-400">Today's logs</h2>
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
      </main>

      <BottomNav tab={tab} onTab={setTab} />
    </div>
  );
}
