/**
 * AI coach panel. Talks to POST /api/chat/stream (SSE): consumes `delta`
 * events to render the assistant message progressively and a `proposal`
 * event to render the interactive Proposal Card.
 */
import { useRef, useState } from "react";
import { Send } from "lucide-react";
import { Button } from "./ui/button";
import type { ProposalItem } from "../lib/types";
import { ProposalCard, type ProposalCardItem } from "./ProposalCard";

interface Message {
  role: "user" | "assistant";
  text: string;
}

export function Assistant() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [proposal, setProposal] = useState<ProposalCardItem[] | null>(null);
  const sessionId = useRef(crypto.randomUUID());

  const patchLast = (text: string) =>
    setMessages((m) => {
      const copy = [...m];
      copy[copy.length - 1] = { role: "assistant", text };
      return copy;
    });

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setProposal(null);
    setMessages((m) => [...m, { role: "user", text }, { role: "assistant", text: "" }]);
    let assistantText = "";

    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ message: text, session_id: sessionId.current }),
      });
      if (!res.ok || !res.body) throw new Error(`Chat failed (${res.status})`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const eventLine = frame.split("\n").find((l) => l.startsWith("event: "));
          const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
          if (!eventLine || !dataLine) continue;
          const event = eventLine.slice(7).trim();
          const data = JSON.parse(dataLine.slice(6)) as Record<string, unknown>;
          if (event === "delta") {
            assistantText += String(data.text ?? "");
            patchLast(assistantText);
          } else if (event === "proposal") {
            const items = data.proposed_items as ProposalItem[] | undefined;
            if (items?.length) {
              setProposal(
                items.map((p) => ({
                  name: p.name,
                  per100: p.per100,
                  quantityG: p.estimated_weight_g,
                  confidence: p.confidence,
                  reasoning: p.reasoning,
                  sourceType: "text_estimate" as const,
                })),
              );
            }
          } else if (event === "error") {
            assistantText += `\n⚠️ ${String(data.message ?? "unknown error")}`;
            patchLast(assistantText);
          }
        }
      }
    } catch (err) {
      patchLast(`⚠️ ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-base font-semibold">AI Coach</h2>

      {messages.length === 0 && (
        <p className="text-sm text-zinc-500">
          Describe what you ate — e.g. “1.5 cans of drained tuna with 100g pasta
          and 1 tbsp olive oil” — and review the proposal before it’s logged.
        </p>
      )}

      <div className="space-y-3">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={msg.role === "user" ? "text-right" : "text-left"}
          >
            <span
              className={
                msg.role === "user"
                  ? "inline-block max-w-[85%] rounded-xl bg-zinc-800 px-3 py-2 text-sm"
                  : "inline-block max-w-[85%] rounded-xl bg-zinc-900 px-3 py-2 text-sm text-zinc-200"
              }
            >
              {msg.text}
            </span>
          </div>
        ))}
      </div>

      {proposal && <ProposalCard items={proposal} onDone={() => setProposal(null)} />}

      <div className="flex gap-2 pb-safe">
        <input
          className="flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
          placeholder="I had…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void send()}
          disabled={busy}
        />
        <Button onClick={() => void send()} disabled={busy || !input.trim()} aria-label="Send">
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
