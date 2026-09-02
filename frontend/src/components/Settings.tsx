/**
 * Settings screen (decisions D34/D35): per-task LLM providers, editable at
 * runtime. API keys are write-only — the server never echoes them back, so
 * an empty key input means "leave the stored key alone".
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Link2, Loader2, X } from "lucide-react";
import { api } from "../lib/api";
import type {
  MeInfo,
  RuntimeSettings,
  RuntimeSettingsInput,
  UserRecord,
} from "../lib/types";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { PushSettings } from "./PushSettings";

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
    textModel: "gemini-3.6-flash",
    visionModel: "gemini-3.6-flash",
  },
  {
    id: "ollama",
    label: "Ollama",
    baseUrl: "http://localhost:11434/v1",
    textModel: "qwen2.5:7b",
    visionModel: "qwen2.5vl:7b",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com",
    textModel: "deepseek-v4-flash",
    visionModel: "deepseek-v4-flash-vision-exp",
  },
];

const eyebrow = "text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-500";
const field =
  "w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm placeholder:text-zinc-600 focus:border-emerald-600 focus:outline-none";
const monoField = `${field} font-mono text-xs`;

function statusLine(s: TaskStatus) {
  if (s?.busy)
    return (
      <span className="flex items-center gap-1.5 text-xs text-zinc-500">
        <Loader2 className="h-3 w-3 animate-spin" /> {"Testing\u2026"}
      </span>
    );
  if (!s) return null;
  return (
    <span className={`text-xs ${s.ok ? "text-emerald-400" : "text-red-400"}`}>
      {s.ok ? "OK \u00b7 " : ""}
      {s.detail}
    </span>
  );
}

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
        {vision && matchedPreset?.id === "deepseek" && (
          <p className="mt-2 text-[11px] leading-relaxed text-amber-400/80">
            DeepSeek vision is experimental. Label images are sent to DeepSeek's hosted API.
          </p>
        )}
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
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className={eyebrow}>API key {hasStoredKey && !typed && !clearing ? "(saved)" : ""}</span>
        <span className="text-[10px] text-zinc-600">Write-only · never displayed again</span>
      </div>
      {!clearing && (
        <input
          type="password"
          className={field}
          placeholder={hasStoredKey ? "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 saved \u2014 type to replace" : "Enter this provider's API key"}
          value={typed}
          onChange={(e) => onType(e.target.value)}
          autoComplete="new-password"
        />
      )}
      {!hasStoredKey && !typed && !clearing && (
        <p className="text-[11px] text-zinc-600">
          Required for hosted providers unless a fallback key is already configured on the server. Local Ollama usually needs no key.
        </p>
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
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<MeInfo>("/api/auth/me") });
  const isAdmin = me.data?.is_admin === true;
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<RuntimeSettings>("/api/settings"),
    enabled: isAdmin,
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

  if (settings.isLoading || (isAdmin && (!f || !data))) {
    return <div className="h-64 animate-pulse rounded-xl bg-zinc-900" />;
  }

  const patch = (p: Partial<FormState>) => setForm({ ...f!, ...p });

  const providerCards = data && f ? (
    <>
      <Card className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Coach replies</h3>
          <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">text</span>
        </div>
        <ProviderFields
          baseUrl={f.textBaseUrl}
          model={f.textModel}
          onBaseUrl={(v) => patch({ textBaseUrl: v })}
          onModel={(v) => patch({ textModel: v })}
          vision={false}
        />
        {f.textBaseUrl.trim() === "https://api.deepseek.com" && f.visionInherit && (
          <p className="rounded-lg border border-amber-900/50 bg-amber-950/20 px-3 py-2 text-[11px] leading-relaxed text-amber-300/90">
            DeepSeek's text model cannot read images. Enable a separate label-scanning provider and select DeepSeek's experimental vision model or another vision provider.
          </p>
        )}
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
          <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">vision</span>
        </div>
        {f.visionInherit ? (
          <p className="text-xs text-zinc-500">
            Uses the coach provider above. Split it when you want a cheap text model and a stronger vision model.
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

      <div className="sticky bottom-2 space-y-2 md:static">
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
    </>
  ) : null;

  return (
    <section className="mx-auto max-w-xl space-y-4 lg:max-w-2xl">
      <AccountCard />
      {me.data && <PushSettings accountId={me.data.id} />}

      {isAdmin ? (
        <>
          <header className="space-y-1 pt-2">
            <h2 className="text-base font-semibold tracking-tight">AI providers</h2>
            <p className="text-xs leading-relaxed text-zinc-500">
              Coach replies and label scanning can use different providers. Keys are stored server-side and never shown again.
            </p>
          </header>
          {providerCards}
          <UsersCard />
        </>
      ) : (
        <p className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3 text-xs text-zinc-500">
          Provider configuration is managed by an admin account.
        </p>
      )}
    </section>
  );
}

function AccountCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [state, setState] = useState<{ ok: boolean; msg: string } | null>(null);
  const change = useMutation({
    mutationFn: () =>
      api("/api/users/me/password", {
        method: "PATCH",
        body: JSON.stringify({ current_password: current, new_password: next }),
      }),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setState({ ok: true, msg: "Password updated" });
    },
    onError: (err) => setState({ ok: false, msg: err.message }),
  });
  return (
    <Card className="space-y-3">
      <h3 className="text-sm font-semibold">Your password</h3>
      <input type="password" className={field} placeholder="Current password" value={current}
        onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
      <input type="password" className={field} placeholder={`New password (${12}+ characters)`} value={next}
        onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
      {state && <p className={`text-xs ${state.ok ? "text-emerald-400" : "text-red-400"}`}>{state.msg}</p>}
      <Button size="sm" disabled={!current || !next || change.isPending} onClick={() => change.mutate()}>
        Update password
      </Button>
    </Card>
  );
}

function UsersCard() {
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<UserRecord[]>("/api/users") });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [resets, setResets] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const create = useMutation({
    mutationFn: () =>
      api("/api/users", { method: "POST", body: JSON.stringify({ username: username.trim(), password }) }),
    onSuccess: async () => {
      setUsername("");
      setPassword("");
      setMsg({ ok: true, text: "Account created" });
      await qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (err) => setMsg({ ok: false, text: err.message }),
  });
  const reset = useMutation({
    mutationFn: ({ id, newPassword }: { id: string; newPassword: string }) =>
      api(`/api/users/${id}/password`, { method: "PATCH", body: JSON.stringify({ new_password: newPassword }) }),
    onSuccess: async (_d, vars) => {
      setMsg({ ok: true, text: `Password reset for ${vars.id.slice(0, 8)}\u2026` });
      setResets((r) => ({ ...r, [vars.id]: "" }));
    },
    onError: (err) => setMsg({ ok: false, text: err.message }),
  });

  return (
    <Card className="space-y-4">
      <h3 className="text-sm font-semibold">Accounts</h3>
      {msg && <p className={`text-xs ${msg.ok ? "text-emerald-400" : "text-red-400"}`}>{msg.text}</p>}
      <div className="space-y-2">
        {(users.data ?? []).map((u) => (
          <div key={u.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-zinc-800 p-2.5">
            <span className="min-w-24 text-sm text-zinc-200">{u.username}</span>
            {u.is_admin && (
              <span className="rounded border border-zinc-700 px-1 py-px text-[9px] uppercase tracking-wide text-zinc-500">
                admin
              </span>
            )}
            <input
              type="password"
              className={`${field} ml-auto h-8 w-44 py-1 text-xs`}
              placeholder="New password"
              value={resets[u.id] ?? ""}
              onChange={(e) => setResets((r) => ({ ...r, [u.id]: e.target.value }))}
              autoComplete="new-password"
            />
            <Button
              variant="outline"
              size="sm"
              disabled={!(resets[u.id] ?? "").length || reset.isPending}
              onClick={() => reset.mutate({ id: u.id, newPassword: resets[u.id] })}
            >
              Reset
            </Button>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-zinc-800 pt-3">
        <input className={`${field} h-9 w-36 py-1 text-sm`} placeholder="username" value={username}
          onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
        <input type="password" className={`${field} h-9 w-44 py-1 text-sm`} placeholder="password" value={password}
          onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        <Button size="sm" disabled={!username.trim() || !password || create.isPending} onClick={() => create.mutate()}>
          Add account
        </Button>
      </div>
    </Card>
  );
}
