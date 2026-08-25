/**
 * Settings screen (decisions D34/D35): per-task LLM providers, editable at
 * runtime. API keys are write-only — the server never echoes them back, so
 * an empty key input means "leave the stored key alone".
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Link2, Loader2, X } from "lucide-react";
import { api } from "../lib/api";
import type { RuntimeSettings, RuntimeSettingsInput } from "../lib/types";
import { Button } from "./ui/button";
import { Card } from "./ui/card";

interface Preset {
  id: string;
  label: string;
  baseUrl: string;
  textModel: string;
  visionModel?: string;
}

const PRESETS: Preset[] = [
  {
    id: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    textModel: "gpt-4o-mini",
    visionModel: "gpt-4o-mini",
  },
  {
    id: "gemini",
    label: "Gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    textModel: "gemini-2.0-flash",
    visionModel: "gemini-2.0-flash",
  },
  {
    id: "ollama",
    label: "Ollama",
    baseUrl: "http://localhost:11434/v1",
    textModel: "qwen2.5:7b",
    visionModel: "qwen2.5vl:7b",
  },
];

const eyebrow = "text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-500";
const field =
  "w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm placeholder:text-zinc-600 focus:border-emerald-600 focus:outline-none";
const monoField = `${field} font-mono text-xs`;

type TaskStatus = { busy: boolean; ok: boolean; detail: string } | null;

interface FormState {
  textBaseUrl: string;
  textModel: string;
  textKey: string;
  clearTextKey: boolean;
  visionInherit: boolean;
  visionBaseUrl: string;
  visionModel: string;
  visionKey: string;
  clearVisionKey: boolean;
  offBaseUrl: string;
}

function toForm(s: RuntimeSettings): FormState {
  return {
    textBaseUrl: s.text.base_url ?? "",
    textModel: s.text.model ?? "",
    textKey: "",
    clearTextKey: false,
    visionInherit: s.vision_inherits_text,
    visionBaseUrl: s.vision.base_url ?? "",
    visionModel: s.vision.model ?? "",
    visionKey: "",
    clearVisionKey: false,
    offBaseUrl: s.openfoodfacts_base_url ?? "",
  };
}

function buildPayload(f: FormState): RuntimeSettingsInput {
  const apiKey = (typed: string, clear: boolean) =>
    typed ? { api_key: typed } : clear ? { api_key: "" } : {};
  return {
    text: {
      base_url: f.textBaseUrl.trim() || null,
      model: f.textModel.trim() || null,
      ...apiKey(f.textKey.trim(), f.clearTextKey),
    },
    vision: {
      inherit_text: f.visionInherit,
      base_url: f.visionInherit ? null : f.visionBaseUrl.trim() || null,
      model: f.visionInherit ? null : f.visionModel.trim() || null,
      ...(f.visionInherit
        ? {}
        : apiKey(f.visionKey.trim(), f.clearVisionKey)),
    },
    openfoodfacts_base_url: f.offBaseUrl.trim() || null,
  };
}

function ProviderFields(props: {
  baseUrl: string;
  model: string;
  onBaseUrl: (v: string) => void;
  onModel: (v: string) => void;
  vision: boolean;
}) {
  const { baseUrl, model, onBaseUrl, onModel, vision } = props;
  const matchedPreset = PRESETS.find((p) => p.baseUrl === baseUrl.trim());
  return (
    <div className="space-y-3">
      <div>
        <p className={`${eyebrow} mb-1.5`}>Provider</p>
        <div className="flex flex-wrap gap-1.5">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                onBaseUrl(p.baseUrl);
                onModel(vision ? (p.visionModel ?? p.textModel) : p.textModel);
              }}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                matchedPreset?.id === p.id
                  ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-300"
                  : "border-zinc-700 text-zinc-400 hover:border-zinc-600 hover:text-zinc-300"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <label className="block space-y-1">
        <span className={eyebrow}>Endpoint</span>
        <input
          className={monoField}
          placeholder="https://api.openai.com/v1"
          value={baseUrl}
          onChange={(e) => onBaseUrl(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
      </label>
      <label className="block space-y-1">
        <span className={eyebrow}>Model</span>
        <input
          className={monoField}
          placeholder="gpt-4o-mini"
          value={model}
          onChange={(e) => onModel(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
      </label>
    </div>
  );
}

function KeyRow(props: {
  hasStoredKey: boolean;
  typed: string;
  clearing: boolean;
  onType: (v: string) => void;
  onClearToggle: () => void;
}) {
  const { hasStoredKey, typed, clearing, onType, onClearToggle } = props;
  if (!hasStoredKey && !typed && !clearing) return null;
  return (
    <div className="space-y-1">
      <span className={eyebrow}>API key {hasStoredKey && !typed && !clearing ? "(saved)" : ""}</span>
      {!clearing && (
        <input
          type="password"
          className={field}
          placeholder={hasStoredKey ? "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 saved \u2014 type to replace" : "sk-\u2026"}
          value={typed}
          onChange={(e) => onType(e.target.value)}
          autoComplete="new-password"
        />
      )}
      {hasStoredKey && (
        <button
          type="button"
          onClick={onClearToggle}
          className="text-[11px] text-red-400/90 underline-offset-2 hover:underline"
        >
          {clearing ? "Keep saved key" : "Remove saved key"}
        </button>
      )}
    </div>
  );
}

export function SettingsView() {
  const qc = useQueryClient();
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<RuntimeSettings>("/api/settings"),
  });
  const [form, setForm] = useState<FormState | null>(null);
  const [saveState, setSaveState] = useState<{ ok: boolean; msg: string } | null>(null);
  const [textTest, setTextTest] = useState<TaskStatus>(null);
  const [visionTest, setVisionTest] = useState<TaskStatus>(null);

  const data = settings.data;
  const loadedForm = useMemo(() => (data ? toForm(data) : null), [data]);
  const f = form ?? loadedForm;

  const dirty =
    !!f && !!loadedForm && JSON.stringify(f) !== JSON.stringify(loadedForm);

  const save = useMutation({
    mutationFn: (payload: RuntimeSettingsInput) =>
      api<RuntimeSettings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    onSuccess: async (saved) => {
      await qc.invalidateQueries({ queryKey: ["settings"] });
      setForm(toForm(saved));
      setSaveState({ ok: true, msg: "Saved \u00b7 live immediately" });
    },
    onError: (err) => setSaveState({ ok: false, msg: err.message }),
  });

  const runTest = async (task: "text" | "vision") => {
    const setter = task === "text" ? setTextTest : setVisionTest;
    setter({ busy: true, ok: true, detail: "" });
    try {
      const r = await api<{ ok: boolean; detail: string }>("/api/settings/test", {
        method: "POST",
        body: JSON.stringify({ task }),
      });
      setter({ busy: false, ok: r.ok, detail: r.detail });
    } catch (err) {
      setter({ busy: false, ok: false, detail: err instanceof Error ? err.message : String(err) });
    }
  };

  if (settings.isLoading || !f || !data) {
    return <div className="h-64 animate-pulse rounded-xl bg-zinc-900" />;
  }

  const patch = (p: Partial<FormState>) => setForm({ ...f, ...p });

  const statusLine = (s: TaskStatus) =>
    s?.busy ? (
      <span className="flex items-center gap-1.5 text-xs text-zinc-500">
        <Loader2 className="h-3 w-3 animate-spin" /> {"Testing\u2026"}
      </span>
    ) : s ? (
      <span className={`text-xs ${s.ok ? "text-emerald-400" : "text-red-400"}`}>
        {s.ok ? "OK \u00b7 " : ""}
        {s.detail}
      </span>
    ) : null;

  return (
    <section className="space-y-4">
      <header className="space-y-1">
        <h2 className="text-base font-semibold tracking-tight">AI providers</h2>
        <p className="text-xs leading-relaxed text-zinc-500">
          Coach replies and label scanning can use different providers. Keys are
          stored server-side and never shown again.
        </p>
      </header>

      <Card className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Coach replies</h3>
          <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">
            text
          </span>
        </div>
        <ProviderFields
          baseUrl={f.textBaseUrl}
          model={f.textModel}
          onBaseUrl={(v) => patch({ textBaseUrl: v })}
          onModel={(v) => patch({ textModel: v })}
          vision={false}
        />
        <KeyRow
          hasStoredKey={data.text.has_api_key}
          typed={f.textKey}
          clearing={f.clearTextKey}
          onType={(v) => patch({ textKey: v, clearTextKey: false })}
          onClearToggle={() => patch({ clearTextKey: !f.clearTextKey })}
        />
        <div className="flex items-center justify-between gap-3 border-t border-zinc-800 pt-3">
          <Button variant="outline" size="sm" disabled={textTest?.busy} onClick={() => void runTest("text")}>
            Test connection
          </Button>
          {statusLine(textTest)}
        </div>
      </Card>

      {/* Signature linkage: vision inherits the coach provider until split. */}
      <div className="relative flex justify-center">
        {f.visionInherit ? (
          <>
            <div className="absolute inset-x-0 top-1/2 border-t border-dashed border-zinc-700" />
            <span className="relative flex items-center gap-1.5 rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-[11px] text-zinc-400">
              <Link2 className="h-3 w-3 text-emerald-400" />
              Same provider as coach
            </span>
          </>
        ) : (
          <span className="rounded-full border border-zinc-800 bg-zinc-900 px-3 py-1 text-[11px] text-zinc-500">
            Separate provider
          </span>
        )}
      </div>

      <Card className={f.visionInherit ? "space-y-3 opacity-80" : "space-y-4"}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Label scanning</h3>
          <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">
            vision
          </span>
        </div>
        {f.visionInherit ? (
          <p className="text-xs text-zinc-500">
            Uses the coach provider above. Split it when you want a cheap text
            model and a stronger vision model.
          </p>
        ) : (
          <>
            <ProviderFields
              baseUrl={f.visionBaseUrl}
              model={f.visionModel}
              onBaseUrl={(v) => patch({ visionBaseUrl: v })}
              onModel={(v) => patch({ visionModel: v })}
              vision
            />
            <KeyRow
              hasStoredKey={data.vision.has_api_key}
              typed={f.visionKey}
              clearing={f.clearVisionKey}
              onType={(v) => patch({ visionKey: v, clearVisionKey: false })}
              onClearToggle={() => patch({ clearVisionKey: !f.clearVisionKey })}
            />
            <div className="flex items-center justify-between gap-3 border-t border-zinc-800 pt-3">
              <Button variant="outline" size="sm" disabled={visionTest?.busy} onClick={() => void runTest("vision")}>
                Test connection
              </Button>
              {statusLine(visionTest)}
            </div>
          </>
        )}
        <label className="flex cursor-pointer items-center justify-between gap-3 border-t border-zinc-800 pt-3">
          <span className="text-xs text-zinc-400">Use a separate provider</span>
          <input
            type="checkbox"
            className="h-4 w-4 accent-emerald-500"
            checked={!f.visionInherit}
            onChange={(e) => patch({ visionInherit: !e.target.checked })}
          />
        </label>
      </Card>

      <Card className="space-y-3">
        <h3 className="text-sm font-semibold">Food database</h3>
        <label className="block space-y-1">
          <span className={eyebrow}>Open Food Facts endpoint</span>
          <input
            className={monoField}
            placeholder="https://world.openfoodfacts.org/api/v2"
            value={f.offBaseUrl}
            onChange={(e) => patch({ offBaseUrl: e.target.value })}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <Button variant="ghost" size="sm" onClick={() => patch({ offBaseUrl: "" })}>
          Reset to default
        </Button>
      </Card>

      <div className="sticky bottom-20 space-y-2">
        {saveState && (
          <p className={`flex items-center gap-1.5 text-xs ${saveState.ok ? "text-emerald-400" : "text-red-400"}`}>
            {saveState.ok ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
            {saveState.msg}
          </p>
        )}
        <div className="flex gap-2">
          <Button
            className="flex-1"
            disabled={!dirty || save.isPending}
            onClick={() => {
              setSaveState(null);
              save.mutate(buildPayload(f));
            }}
          >
            {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save changes"}
          </Button>
          {dirty && (
            <Button variant="outline" onClick={() => { setForm(loadedForm); setSaveState(null); }}>
              Revert
            </Button>
          )}
        </div>
        {dirty && <p className="text-center text-[11px] text-zinc-600">Unsaved changes apply after saving.</p>}
      </div>
    </section>
  );
}
