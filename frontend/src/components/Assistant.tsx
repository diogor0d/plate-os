import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  ArrowUp,
  BarChart3,
  BrainCircuit,
  LoaderCircle,
  Plus,
  ShieldCheck,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import type { AnalyticsIntent, AssistantBlock, AssistantLaunch, AssistantMode } from "../lib/assistant";
import { parseAssistantBlock } from "../lib/assistant";
import { AssistantBlocks } from "./AssistantBlocks";
import { Button } from "./ui/button";

type ResponsePhase = "idle" | "connecting" | "thinking" | "streaming" | "finalizing";

interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  status: "complete" | "pending" | "streaming" | "error";
  blocks?: AssistantBlock[];
}

const starters: {
  label: string;
  description: string;
  prompt: string;
  mode: AssistantMode;
  icon: typeof Sparkles;
}[] = [
  {
    label: "Plan my next meal",
    description: "Use today's remaining targets",
    prompt: "Suggest a practical meal for the rest of today based on my remaining targets.",
    mode: "coach",
    icon: Sparkles,
  },
  {
    label: "Review my goals",
    description: "Draft cautious target changes",
    prompt: "Analyze my current nutrition goals and recent logging, then draft improved goals if the evidence supports a change.",
    mode: "goals",
    icon: Target,
  },
  {
    label: "Find a pattern",
    description: "Read trends and logging gaps",
    prompt: "Analyze my recent logging for useful patterns, data-quality issues, and one action worth taking.",
    mode: "analytics",
    icon: BarChart3,
  },
  {
    label: "Audit AI estimates",
    description: "Find entries worth verifying",
    prompt: "Audit my coach-estimated meal entries and help me identify where verified data would improve accuracy.",
    mode: "analytics",
    icon: ShieldCheck,
  },
];

const thinkingCopy: Record<AssistantMode, string[]> = {
  coach: [
    "Reading today's nutrition picture",
    "Balancing what remains",
    "Shaping a practical answer",
  ],
  goals: [
    "Reviewing your current targets",
    "Checking logging coverage",
    "Drafting a cautious recommendation",
  ],
  analytics: [
    "Reading the selected evidence",
    "Checking patterns and gaps",
    "Preparing the clearest takeaway",
  ],
};

const modeLabels: Record<AssistantMode, string> = {
  coach: "Daily coach",
  goals: "Goal review",
  analytics: "Evidence review",
};

function CoachMark({ active = false }: { active?: boolean }) {
  return (
    <span className={`coach-mark ${active ? "coach-mark-active" : ""}`} aria-hidden="true">
      <span className="coach-mark-orbit" />
      <BrainCircuit className="relative h-4 w-4" />
    </span>
  );
}

function ThinkingIndicator({ label }: { label: string }) {
  return (
    <div className="coach-thinking" role="status" aria-label={label}>
      <div className="coach-thinking-trace" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
      </div>
      <div>
        <p className="text-sm font-medium text-zinc-300">{label}</p>
        <p className="mt-0.5 text-xs text-zinc-600">Working with the context you shared</p>
      </div>
    </div>
  );
}

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
  const [phase, setPhase] = useState<ResponsePhase>("idle");
  const [thinkingStep, setThinkingStep] = useState(0);
  const [mobileNavOffset, setMobileNavOffset] = useState(64);
  const [context, setContext] = useState<AssistantLaunch | null>(null);
  const sessionId = useRef(crypto.randomUUID());
  const appliedLaunch = useRef<string | null>(null);
  const busyRef = useRef(false);
  const threadEnd = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const followThread = useRef(true);

  useEffect(() => {
    if (!launch || appliedLaunch.current === launch.id) return;
    appliedLaunch.current = launch.id;
    setInput(launch.prompt);
    setMode(launch.mode);
    setContext(launch);
    window.setTimeout(() => composer.current?.focus(), 0);
  }, [launch]);

  useEffect(() => {
    if (!busy || phase === "streaming" || phase === "finalizing") return;
    setThinkingStep(0);
    const timer = window.setInterval(() => {
      setThinkingStep((current) => Math.min(current + 1, thinkingCopy[mode].length - 1));
    }, 1800);
    return () => window.clearInterval(timer);
  }, [busy, mode, phase]);

  useEffect(() => {
    const trackPosition = () => {
      const distance = document.documentElement.scrollHeight - window.scrollY - window.innerHeight;
      followThread.current = distance < 180;
    };
    trackPosition();
    window.addEventListener("scroll", trackPosition, { passive: true });
    return () => window.removeEventListener("scroll", trackPosition);
  }, []);

  useEffect(() => {
    if (!followThread.current) return;
    const frame = window.requestAnimationFrame(() => {
      if (!followThread.current) return;
      threadEnd.current?.scrollIntoView({ behavior: "auto", block: "end" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [messages]);

  useEffect(() => {
    const nav = document.querySelector<HTMLElement>('nav[aria-label="Primary"]');
    if (!nav) return;
    const updateOffset = () => setMobileNavOffset(nav.getBoundingClientRect().height + 8);
    updateOffset();
    const observer = new ResizeObserver(updateOffset);
    observer.observe(nav);
    return () => observer.disconnect();
  }, []);

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
    if (composer.current) composer.current.style.height = "auto";
    setBusy(true);
    setPhase("connecting");
    followThread.current = true;
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", text, status: "complete" },
      { id: crypto.randomUUID(), role: "assistant", text: "", status: "pending", blocks: [] },
    ]);
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
          if (event === "meta") {
            setPhase("thinking");
          } else if (event === "delta" && typeof data === "object" && data !== null && "text" in data) {
            setPhase("streaming");
            assistantText += String(data.text ?? "");
            patchLast((message) => ({ ...message, text: assistantText, status: "streaming" }));
          } else if (event === "block" && typeof data === "object" && data !== null && "block" in data) {
            setPhase("finalizing");
            const block = parseAssistantBlock(data.block);
            if (block) patchLast((message) => ({ ...message, blocks: [...(message.blocks ?? []), block] }));
          } else if (event === "error" && typeof data === "object" && data !== null && "message" in data) {
            throw new Error(String(data.message));
          } else if (event === "done") {
            completed = true;
            patchLast((message) => ({ ...message, status: "complete" }));
          }
        }
      }
      if (!completed) throw new Error("The response was interrupted. Try sending your message again.");
    } catch (error) {
      patchLast((message) => ({
        ...message,
        text: error instanceof Error ? error.message : String(error),
        status: "error",
        blocks: [],
      }));
    } finally {
      busyRef.current = false;
      setBusy(false);
      setPhase("idle");
      window.setTimeout(() => composer.current?.focus(), 0);
    }
  };

  const chooseStarter = (starter: (typeof starters)[number]) => {
    setContext(null);
    setMode(starter.mode);
    setInput(starter.prompt);
    window.setTimeout(() => composer.current?.focus(), 0);
  };

  const startNewChat = () => {
    if (busy) return;
    setMessages([]);
    setInput("");
    setContext(null);
    setMode("coach");
    sessionId.current = crypto.randomUUID();
    window.setTimeout(() => composer.current?.focus(), 0);
  };

  const thinkingLabel = phase === "connecting"
    ? "Opening a secure coach session"
    : thinkingCopy[mode][thinkingStep];

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-11rem)] max-w-4xl flex-col md:min-h-[calc(100dvh-16rem)]">
      <header className="flex items-center justify-between gap-4 border-b border-zinc-800/70 pb-4">
        <div className="flex min-w-0 items-center gap-3">
          <CoachMark active={busy} />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-sm font-semibold tracking-tight text-zinc-100">Plate Coach</h2>
              <span className={`h-1 w-1 rounded-full bg-emerald-400 ${busy ? "coach-status-pulse" : ""}`} aria-hidden="true" />
              <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-emerald-500/80">{busy ? "Working" : "Ready"}</span>
            </div>
            <p className="truncate text-xs text-zinc-600">Nutrition context in, reviewable actions out</p>
          </div>
        </div>
        {messages.length > 0 && (
          <Button variant="ghost" size="sm" onClick={startNewChat} disabled={busy} className="shrink-0 text-zinc-400">
            <Plus className="h-3.5 w-3.5" /> New chat
          </Button>
        )}
      </header>

      <div className="flex flex-1 flex-col py-5 md:py-7" aria-busy={busy}>
        {messages.length === 0 ? (
          <div className="coach-empty my-auto flex flex-col items-center py-8 text-center md:py-14">
            <div className="mb-5"><CoachMark /></div>
            <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-emerald-500/70">Context-aware nutrition</p>
            <h3 className="mt-2 text-xl font-semibold tracking-[-0.025em] text-zinc-100 md:text-2xl">What should we work through?</h3>
            <p className="mt-2 max-w-md text-sm leading-relaxed text-zinc-500">
              Ask naturally, or start with a focused review. Nothing is logged or changed without your confirmation.
            </p>
            <div className="mt-7 grid w-full max-w-2xl gap-2 sm:grid-cols-2">
              {starters.map((starter) => {
                const Icon = starter.icon;
                return (
                  <button
                    key={starter.label}
                    type="button"
                    onClick={() => chooseStarter(starter)}
                    className="group flex items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-900/25 px-4 py-3.5 text-left transition-[border-color,background-color,transform] duration-200 hover:-translate-y-0.5 hover:border-zinc-700 hover:bg-zinc-900/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60"
                  >
                    <span className="rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-emerald-400 transition-colors group-hover:border-emerald-900/70 group-hover:bg-emerald-950/20">
                      <Icon className="h-4 w-4" />
                    </span>
                    <span>
                      <span className="block text-sm font-medium text-zinc-300">{starter.label}</span>
                      <span className="mt-0.5 block text-xs text-zinc-600">{starter.description}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="space-y-7" aria-live="polite">
            {messages.map((message) => (
              <div key={message.id} className={message.role === "user" ? "coach-message-user" : "coach-message-assistant"}>
                {message.role === "user" ? (
                  <div className="ml-auto max-w-[88%] rounded-2xl rounded-br-md border border-zinc-700/70 bg-zinc-800/80 px-4 py-3 text-left text-sm leading-relaxed text-zinc-100 md:max-w-[75%]">
                    {message.text}
                  </div>
                ) : (
                  <div className="flex items-start gap-3 md:gap-4">
                    <CoachMark active={message.status === "pending"} />
                    <div className="min-w-0 flex-1 pt-0.5">
                      {message.status === "pending" && !message.text ? (
                        <ThinkingIndicator label={thinkingLabel} />
                      ) : message.status === "error" ? (
                        <div className="rounded-xl border border-red-900/60 bg-red-950/15 px-4 py-3">
                          <p className="text-sm font-medium text-red-300">The coach could not finish that response</p>
                          <p className="mt-1 text-xs leading-relaxed text-red-200/70">{message.text}</p>
                          <p className="mt-2 text-[11px] text-zinc-600">Check the provider connection in Settings, then try again.</p>
                        </div>
                      ) : (
                        <p className="whitespace-pre-wrap text-[15px] leading-7 text-zinc-200">
                          {message.text}
                          {message.status === "streaming" && <span className="coach-caret" aria-hidden="true" />}
                        </p>
                      )}
                      {!!message.blocks?.length && (
                        <div className="mt-4">
                          <AssistantBlocks blocks={message.blocks} onOpenAnalytics={onOpenAnalytics} />
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
            <div ref={threadEnd} />
          </div>
        )}
      </div>

      <div
        className="coach-composer sticky z-[5] -mx-2 bg-zinc-950/90 px-2 pb-2 pt-3 backdrop-blur-xl"
        style={{ "--coach-mobile-nav-offset": `${mobileNavOffset}px` } as CSSProperties}
      >
        {context && (
          <div className="coach-context-chip mb-2 flex items-center justify-between gap-3 rounded-lg border border-emerald-900/50 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-300">
            <span className="flex min-w-0 items-center gap-2">
              <Sparkles className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">
                Using {context.surface === "stats" ? "the current Stats view" : context.surface === "today" ? "today's remaining targets" : "coach context"}
              </span>
            </span>
            <button type="button" onClick={() => setContext(null)} aria-label="Remove attached context" className="rounded p-0.5 text-emerald-500 hover:bg-emerald-900/40 hover:text-emerald-300">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
        <div className="rounded-2xl border border-zinc-700/80 bg-zinc-900/90 p-2 shadow-[0_16px_50px_rgba(0,0,0,0.32)] transition-[border-color,box-shadow] focus-within:border-emerald-700/70 focus-within:shadow-[0_16px_50px_rgba(0,0,0,0.45)]">
          <label htmlFor="coach-message" className="sr-only">Message Plate Coach</label>
          <textarea
            id="coach-message"
            ref={composer}
            rows={1}
            className="max-h-36 min-h-12 w-full resize-none bg-transparent px-2 py-2 text-sm leading-6 text-zinc-100 outline-none placeholder:text-zinc-600"
            placeholder="Ask about a meal, your goals, or a pattern..."
            value={input}
            onChange={(event) => {
              setInput(event.target.value);
              event.currentTarget.style.height = "auto";
              event.currentTarget.style.height = `${Math.min(event.currentTarget.scrollHeight, 144)}px`;
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
            disabled={busy}
          />
          <div className="flex items-center justify-between gap-3 px-1 pb-1">
            <div className="flex min-w-0 items-center gap-2 text-[10px] text-zinc-600">
              <span className="truncate font-medium uppercase tracking-[0.12em]">{modeLabels[mode]}</span>
              <span className="hidden h-1 w-1 rounded-full bg-zinc-700 sm:block" />
              <span className="hidden sm:block">Enter to send · Shift+Enter for a new line</span>
            </div>
            <Button
              size="icon"
              onClick={() => void send()}
              disabled={busy || !input.trim()}
              aria-label={busy ? "Coach is responding" : "Send message"}
              className="h-9 w-9 shrink-0 rounded-full bg-emerald-400 text-zinc-950 hover:bg-emerald-300 disabled:bg-zinc-700 disabled:text-zinc-500"
            >
              {busy ? <LoaderCircle className="coach-spin h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
            </Button>
          </div>
        </div>
        <div className="mt-2 space-y-0.5 text-center text-[10px] leading-relaxed text-zinc-700">
          <p>Messages and selected nutrition context go to your configured provider. Goal review also includes weight and height.</p>
          <p className="flex items-center justify-center gap-1.5"><ShieldCheck className="h-3 w-3" /> Actions remain drafts until you review them.</p>
        </div>
      </div>
    </div>
  );
}
