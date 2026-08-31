import { useEffect, useRef, useState } from "react";
import { BarChart3, Send, Sparkles, Target } from "lucide-react";
import type { AnalyticsIntent, AssistantBlock, AssistantLaunch, AssistantMode } from "../lib/assistant";
import { parseAssistantBlock } from "../lib/assistant";
import { AssistantBlocks } from "./AssistantBlocks";
import { Button } from "./ui/button";

interface Message {
  role: "user" | "assistant";
  text: string;
  blocks?: AssistantBlock[];
}

const starters: { label: string; prompt: string; mode: AssistantMode; icon: typeof Sparkles }[] = [
  { label: "Meal idea", prompt: "Suggest a practical meal for the rest of today based on my remaining targets.", mode: "coach", icon: Sparkles },
  { label: "Review goals", prompt: "Analyze my current nutrition goals and recent logging, then draft improved goals if the evidence supports a change.", mode: "goals", icon: Target },
  { label: "Find patterns", prompt: "Analyze my recent logging for useful patterns, data-quality issues, and one action worth taking.", mode: "analytics", icon: BarChart3 },
];

export function Assistant({
  launch,
  onOpenAnalytics,
}: {
  launch: AssistantLaunch | null;
  onOpenAnalytics: (intent: AnalyticsIntent) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<AssistantMode>("coach");
  const [busy, setBusy] = useState(false);
  const [context, setContext] = useState<AssistantLaunch | null>(null);
  const sessionId = useRef(crypto.randomUUID());
  const appliedLaunch = useRef<string | null>(null);
  const busyRef = useRef(false);

  useEffect(() => {
    if (!launch || appliedLaunch.current === launch.id) return;
    appliedLaunch.current = launch.id;
    setInput(launch.prompt);
    setMode(launch.mode);
    setContext(launch);
  }, [launch]);

  const patchLast = (patch: (message: Message) => Message) =>
    setMessages((current) => {
      if (current.length === 0) return current;
      const copy = [...current];
      copy[copy.length - 1] = patch(copy[copy.length - 1]);
      return copy;
    });

  const send = async () => {
    const text = input.trim();
    if (!text || busyRef.current) return;
    busyRef.current = true;
    setInput("");
    setBusy(true);
    setMessages((current) => [...current, { role: "user", text }, { role: "assistant", text: "", blocks: [] }]);
    let assistantText = "";

    try {
      const requestContext = context;
      const analytics = requestContext?.analytics;
      setContext(null);
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          message: text,
          session_id: sessionId.current,
          mode,
          surface: requestContext?.surface ?? "coach",
          analytics_days: analytics?.days,
          analytics_start: analytics?.start,
          analytics_end: analytics?.end,
          analytics_metric: analytics?.metric,
          analytics_sources: analytics?.sourceTypes ?? [],
          analytics_food_query: analytics?.foodQuery,
        }),
      });
      if (!response.ok || !response.body) throw new Error(`Assistant failed (${response.status})`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const eventLine = frame.split("\n").find((line) => line.startsWith("event: "));
          const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
          if (!eventLine || !dataLine) continue;
          const event = eventLine.slice(7).trim();
          const data: unknown = JSON.parse(dataLine.slice(6));
          if (event === "delta" && typeof data === "object" && data !== null && "text" in data) {
            assistantText += String(data.text ?? "");
            patchLast((message) => ({ ...message, text: assistantText }));
          } else if (event === "block" && typeof data === "object" && data !== null && "block" in data) {
            const block = parseAssistantBlock(data.block);
            if (block) patchLast((message) => ({ ...message, blocks: [...(message.blocks ?? []), block] }));
          } else if (event === "error" && typeof data === "object" && data !== null && "message" in data) {
            throw new Error(String(data.message));
          } else if (event === "done") {
            completed = true;
          }
        }
      }
      if (!completed) throw new Error("The assistant response was interrupted. Please try again.");
    } catch (error) {
      patchLast((message) => ({ ...message, text: error instanceof Error ? error.message : String(error), blocks: [] }));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const chooseStarter = (starter: (typeof starters)[number]) => {
    setContext(null);
    setMode(starter.mode);
    setInput(starter.prompt);
  };

  return (
    <div className="mx-auto grid max-w-5xl gap-5 lg:grid-cols-[minmax(0,1fr)_240px]">
      <section className="space-y-4" aria-busy={busy}>
        {context && (
          <div className="rounded-lg border border-emerald-900/50 bg-emerald-950/10 px-3 py-2 text-xs text-emerald-300">
            Context attached · {context.surface === "stats" ? "current Stats view" : context.surface === "today" ? "today's budget" : "coach"}
          </div>
        )}

        {messages.length === 0 && (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/35 p-5">
            <p className="text-sm leading-relaxed text-zinc-400">
              Ask for a meal idea, inspect your logging patterns, or draft new goals. PlateOS can render trusted actions, but meals and goals still require your review.
            </p>
          </div>
        )}

        <div className="space-y-4" aria-live="polite">
          {messages.map((message, index) => (
            <div key={index} className={message.role === "user" ? "text-right" : "text-left"}>
              <div className={message.role === "user" ? "ml-auto max-w-[85%] rounded-xl bg-zinc-800 px-3 py-2 text-left text-sm" : "max-w-[92%] space-y-3"}>
                {message.role === "assistant" ? (
                  <>
                    <p className="rounded-xl bg-zinc-900 px-3 py-2 text-sm leading-relaxed text-zinc-200">{message.text || (busy ? "Thinking..." : "")}</p>
                    {message.blocks && <AssistantBlocks blocks={message.blocks} onOpenAnalytics={onOpenAnalytics} />}
                  </>
                ) : message.text}
              </div>
            </div>
          ))}
        </div>

        <div className="flex gap-2 pb-safe">
          <textarea
            className="min-h-11 flex-1 resize-y rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm focus:border-emerald-600 focus:outline-none"
            placeholder="Ask about meals, goals, or patterns..."
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); }
            }}
            disabled={busy}
          />
          <Button onClick={() => void send()} disabled={busy || !input.trim()} aria-label="Send"><Send className="h-4 w-4" /></Button>
        </div>
        <p className="text-[11px] leading-relaxed text-zinc-600">
          Messages and selected nutrition context are sent to your configured text provider. Goal review also includes current weight and height. Use a local provider to keep this data on-host.
        </p>
      </section>

      <aside className="space-y-2 lg:sticky lg:top-[105px] lg:self-start">
        <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-600">Harness actions</p>
        {starters.map((starter) => {
          const Icon = starter.icon;
          return (
            <button key={starter.label} type="button" onClick={() => chooseStarter(starter)} className="flex w-full items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-900/40 px-3 py-3 text-left transition-colors hover:border-zinc-700 hover:bg-zinc-900">
              <Icon className="h-4 w-4 text-emerald-400" />
              <span className="text-xs font-medium text-zinc-300">{starter.label}</span>
            </button>
          );
        })}
        <button type="button" onClick={() => { setContext(null); setMode("analytics"); setInput("Audit my coach-estimated meal entries and help me identify where verified data would improve accuracy."); }} className="w-full rounded-xl border border-dashed border-zinc-800 px-3 py-2.5 text-left text-xs text-zinc-500 hover:border-zinc-700 hover:text-zinc-300">
          Audit AI estimates
        </button>
      </aside>
    </div>
  );
}
