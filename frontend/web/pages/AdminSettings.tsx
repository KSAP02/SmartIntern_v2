import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { ExternalLink, FileCog, RefreshCw } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import type {
  AdminSection,
  AdminSettings as Settings,
  AdminSettingsOut,
  LimitsSettings,
  LLMTaskOverride,
  MatchingSettings,
  ModelsSettings,
  ApiCallOut,
  JSearchTestOut,
  QuotaOut,
  ScheduleSettings,
  SourceOut,
  SourcesSettings,
} from "../lib/types";
import { timeAgo, useResource } from "../lib/util";
import { Badge, Button, ErrorBanner, Input, PageHeader, Segmented, Skeleton, Toggle } from "../components/ui";
import { useToast } from "../components/Toast";
import { ChipInput } from "../components/ChipInput";
import { Field, MoreOptions, NumInput, Section, SectionNav, Select, SwitchRow, same } from "../components/settings/form";

const SECTIONS: { id: AdminSection; label: string }[] = [
  { id: "models", label: "Models" },
  { id: "matching", label: "Matching" },
  { id: "sources", label: "JSearch" },
  { id: "schedule", label: "Schedule" },
  { id: "limits", label: "Limits & retention" },
];
const LABEL = Object.fromEntries(SECTIONS.map((s) => [s.id, s.label])) as Record<AdminSection, string>;

const EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"];
const TIMEZONES = ["Asia/Kolkata", "UTC", "Europe/London", "America/New_York", "America/Los_Angeles", "Asia/Singapore"];
const POLL_MS = 5000;

// ── Models ─────────────────────────────────────────────────────────────────────

function EffortSelect({ value, onChange, empty, id }: { value: string | null; onChange: (v: string | null) => void; empty: string; id?: string }) {
  const opts = value && !EFFORTS.includes(value) ? [value, ...EFFORTS] : EFFORTS;
  return (
    <Select id={id} className="w-full" value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{empty}</option>
      {opts.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </Select>
  );
}

function TaskRow({ name, v, set }: { name: string; v: LLMTaskOverride; set: (v: LLMTaskOverride) => void }) {
  return (
    <tr>
      <td className="px-3 py-2 font-mono text-xs text-zinc-700 dark:text-zinc-300">{name}</td>
      <td className="px-3 py-2">
        <NumInput ariaLabel={`${name} temperature`} nullable min={0} max={2} step={0.1} placeholder="inherit" value={v.temperature} onChange={(temperature) => set({ ...v, temperature })} className="w-24" />
      </td>
      <td className="px-3 py-2">
        <EffortSelect value={v.reasoning_effort} onChange={(reasoning_effort) => set({ ...v, reasoning_effort })} empty="inherit" />
      </td>
      <td className="px-3 py-2">
        <NumInput ariaLabel={`${name} max output tokens`} nullable min={1} step={500} placeholder="inherit" value={v.max_output_tokens} onChange={(n) => set({ ...v, max_output_tokens: n == null ? null : Math.round(n) })} className="w-28" />
      </td>
    </tr>
  );
}

function ModelsFields({ v, saved, set, env }: { v: ModelsSettings; saved: ModelsSettings; set: (v: ModelsSettings) => void; env: Record<string, string> }) {
  const llm = (p: Partial<ModelsSettings["llm"]>) => set({ ...v, llm: { ...v.llm, ...p } });
  const emb = (p: Partial<ModelsSettings["embedding"]>) => set({ ...v, embedding: { ...v.embedding, ...p } });
  const reembed = v.embedding.model !== saved.embedding.model || v.embedding.dimensions !== saved.embedding.dimensions;
  const envNote = (key: string) => (env[key] ? <span className="text-amber-700 dark:text-amber-400">.env overrides this with “{env[key]}”.</span> : undefined);
  const tasks = Object.keys(v.tasks).sort();
  return (
    <>
      <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-400">LLM (chat model)</h3>
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Provider" htmlFor="llm-provider" hint={envNote("llm.provider") ?? "openai (others need a branch in backend/model.py)."}>
          <Input id="llm-provider" value={v.llm.provider} onChange={(e) => llm({ provider: e.target.value })} spellCheck={false} />
        </Field>
        <Field label="Model" htmlFor="llm-model" hint={envNote("llm.model") ?? "The provider's model id, e.g. gpt-6-luna."}>
          <Input id="llm-model" value={v.llm.model} onChange={(e) => llm({ model: e.target.value })} spellCheck={false} className="font-mono" />
        </Field>
        <Field label="Reasoning effort" htmlFor="llm-effort" hint="More = slower and costlier.">
          <EffortSelect id="llm-effort" value={v.llm.reasoning_effort} onChange={(reasoning_effort) => llm({ reasoning_effort })} empty="Model default" />
        </Field>
        <Field label="Temperature" htmlFor="llm-temp" hint="0 = deterministic, up to 2. Empty = not sent. Skipped if the model doesn't accept it.">
          <NumInput id="llm-temp" nullable min={0} max={2} step={0.1} placeholder="not set" value={v.llm.temperature} onChange={(temperature) => llm({ temperature })} className="w-32" />
        </Field>
      </div>
      <MoreOptions label="Limits and per-task overrides">
        <div className="grid gap-5 sm:grid-cols-3">
          <Field label="Max output tokens" htmlFor="llm-max">
            <NumInput id="llm-max" min={1} step={500} value={v.llm.max_output_tokens} onChange={(n) => n != null && llm({ max_output_tokens: Math.round(n) })} />
          </Field>
          <Field label="Timeout (s)" htmlFor="llm-timeout">
            <NumInput id="llm-timeout" min={1} step={5} value={v.llm.timeout_seconds} onChange={(n) => n != null && llm({ timeout_seconds: n })} />
          </Field>
          <Field label="Retries" htmlFor="llm-retries">
            <NumInput id="llm-retries" min={0} step={1} value={v.llm.max_retries} onChange={(n) => n != null && llm({ max_retries: Math.round(n) })} />
          </Field>
        </div>
        {tasks.length > 0 && (
          <div>
            <p className="mb-2 text-xs text-zinc-500">Per task ([llm.tasks.*]). Empty = inherit the values above.</p>
            <div className="overflow-x-auto rounded-md border border-zinc-200 dark:border-zinc-800">
              <table className="w-full min-w-[34rem] text-left text-sm">
                <thead>
                  <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
                    <th className="px-3 py-2 font-medium">Task</th>
                    <th className="px-3 py-2 font-medium">Temperature</th>
                    <th className="px-3 py-2 font-medium">Reasoning effort</th>
                    <th className="px-3 py-2 font-medium">Max output tokens</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {tasks.map((t) => (
                    <TaskRow key={t} name={t} v={v.tasks[t]} set={(o) => set({ ...v, tasks: { ...v.tasks, [t]: o } })} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </MoreOptions>

      <h3 className="border-t border-zinc-100 pt-5 text-xs font-medium uppercase tracking-wide text-zinc-400 dark:border-zinc-800">Embeddings</h3>
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Model" htmlFor="emb-model" hint="Used for memory cards, jobs and requirements.">
          <Input id="emb-model" value={v.embedding.model} onChange={(e) => emb({ model: e.target.value })} spellCheck={false} className="font-mono" />
        </Field>
        <Field label="Dimensions" htmlFor="emb-dims">
          <NumInput id="emb-dims" min={1} step={256} value={v.embedding.dimensions} onChange={(n) => n != null && emb({ dimensions: Math.round(n) })} />
        </Field>
        <Field label="Provider" htmlFor="emb-provider">
          <Input id="emb-provider" value={v.embedding.provider} onChange={(e) => emb({ provider: e.target.value })} spellCheck={false} />
        </Field>
        <Field label="Batch size" htmlFor="emb-batch" hint="Texts per API call.">
          <NumInput id="emb-batch" min={1} step={16} value={v.embedding.batch_size} onChange={(n) => n != null && emb({ batch_size: Math.round(n) })} />
        </Field>
      </div>
      {reembed && (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          Changing the embedding model or dimensions rebuilds every vector: your memory cards and all gathered jobs are re-embedded (a few cents) after you save.
        </p>
      )}
    </>
  );
}

// ── Matching ───────────────────────────────────────────────────────────────────

function MatchingFields({ v, saved, set }: { v: MatchingSettings; saved: MatchingSettings; set: (v: MatchingSettings) => void }) {
  const unit = (k: "role_threshold" | "borderline_role_threshold" | "borderline_context_threshold", label: string, hint: string) => (
    <Field label={label} htmlFor={`m-${k}`} hint={hint}>
      <NumInput id={`m-${k}`} min={0} max={1} step={0.01} value={v[k]} onChange={(n) => n != null && set({ ...v, [k]: n })} />
    </Field>
  );
  return (
    <>
      <div className="grid gap-5 sm:grid-cols-2">
        {unit("role_threshold", "Role threshold", "0–1. Job title (best part, abbreviations expanded) vs your closest role. Measured: relevant titles 0.78–1.0, unrelated 0.5–0.67.")}
        {unit("borderline_role_threshold", "Borderline title", "0–1. A title at least this close still counts if the job text also matches that role's context (below). 0 = off.")}
        {unit("borderline_context_threshold", "Borderline role-context match", "0–1. Job text vs the role's context (Memory ▾ Role contexts) needed to rescue a borderline title. Also ranks Matches.")}
      </div>
      {v.borderline_role_threshold > v.role_threshold && <p className="text-xs text-rose-600/80 dark:text-rose-400/80">The borderline title threshold should be lower than the role threshold.</p>}
      <p className="text-xs text-zinc-500">Requirements are checked by named skills you have (exact) and years; memory cards are no longer embedded.</p>
      <MoreOptions label="Metric">
        <Field label="Metric" hint={v.metric !== saved.metric ? <span className="text-amber-700 dark:text-amber-400">Changing the metric rebuilds and re-embeds every vector after you save.</span> : "Same ranking for OpenAI embeddings; changing it rebuilds vectors."}>
          <Segmented
            value={v.metric}
            onChange={(metric) => set({ ...v, metric })}
            options={[
              { value: "COSINE", label: "Cosine" },
              { value: "IP", label: "Inner product" },
              { value: "L2", label: "L2" },
            ]}
          />
        </Field>
      </MoreOptions>
    </>
  );
}

// ── Sources ────────────────────────────────────────────────────────────────────

/** One real request from the reserve, exactly as a scan would send it for your top search. */
function JSearchTest({ configured }: { configured: boolean }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState<JSearchTestOut | null>(null);
  const run = async () => {
    setBusy(true);
    try {
      const r = await api.testJSearch();
      setOut(r);
      if (!r.ok) toast.error("Test request failed", r.error ?? undefined);
    } catch (e) {
      toast.error("Test request failed", errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const india = out ? (out.countries.IN ?? 0) : 0;
  return (
    <div className="rounded-md border border-dashed border-zinc-300 p-4 dark:border-zinc-700">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-zinc-800 dark:text-zinc-200">Test with 1 request</p>
          <p className="text-[11px] text-zinc-500">Spends one request from the reserve on your top search, shows what came back, and keeps the jobs.</p>
        </div>
        <Button size="sm" loading={busy} disabled={!configured} onClick={() => void run()}>
          Run test (1 request)
        </Button>
      </div>
      {out && (
        <div className="mt-3 border-t border-zinc-100 pt-3 text-xs text-zinc-600 dark:border-zinc-800 dark:text-zinc-400">
          {out.query && <p className="text-zinc-800 dark:text-zinc-200">“{out.query}”</p>}
          {out.ok ? (
            <>
              <p className="mt-1">
                {out.results} jobs returned · {out.new_jobs} new · {out.relevant_jobs} relevant · {india} in India · {out.has_highlights} with requirement lists · {out.has_currency} with salary currency
              </p>
              {Object.keys(out.publishers).length > 0 && <p className="mt-1">Posted on: {Object.entries(out.publishers).map(([k, n]) => `${k} (${n})`).join(", ")}</p>}
              {out.titles.length > 0 && <p className="mt-1">Titles: {out.titles.join(" · ")}</p>}
              {out.saved_as && <p className="mt-1 text-zinc-400">Raw answer saved as {out.saved_as} (app data folder).</p>}
            </>
          ) : (
            <p className="mt-1 text-rose-600/80 dark:text-rose-400/80">{out.error}</p>
          )}
        </div>
      )}
    </div>
  );
}

/** How the billing period is going (scan requests; the reserve isn't counted), worked out from
 *  the request log, plus what the daily switch as set here would allow today. */
function BudgetStatus({ on, perDay, onUsePace }: { on: boolean; perDay: number; onUsePace: (n: number) => void }) {
  const [q, setQ] = useState<QuotaOut | null>(null);
  useEffect(() => {
    void api
      .getJSearchAnalytics(1)
      .then((a) => setQ(a.quota))
      .catch(() => setQ(null));
  }, []);
  if (!q) return null;
  const leftToday = on ? Math.max(0, Math.min(q.scan_left, perDay - q.today_used)) : q.scan_left;
  const ahead = q.ahead_by;
  return (
    <div className="rounded-md bg-zinc-50 px-3 py-2.5 text-xs text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
      <p className="tabular-nums">
        This period: <span className="text-zinc-900 dark:text-zinc-100">{q.scan_used}</span> of {q.scan_budget} scan requests used ·{" "}
        <span className="text-zinc-900 dark:text-zinc-100">{q.scan_left}</span> left · {q.days_left} day{q.days_left === 1 ? "" : "s"} left (resets {q.resets_on}) · today {q.today_used} used
      </p>
      <p className="mt-1 tabular-nums">
        An even pace would have used {q.expected_by_today} by the end of today:{" "}
        {ahead > 0 ? (
          <span className="text-amber-700 dark:text-amber-400">{ahead} more than that (spending faster)</span>
        ) : ahead < 0 ? (
          <span className="text-zinc-900 dark:text-zinc-100">{-ahead} fewer (room to spare)</span>
        ) : (
          "exactly on pace"
        )}
        . Even pace from now: <span className="text-zinc-900 dark:text-zinc-100">{q.even_pace} a day</span>.
        {(!on || perDay !== q.even_pace) && q.even_pace > 0 && (
          <button type="button" className="ml-2 text-violet-700 hover:underline dark:text-violet-300" onClick={() => onUsePace(q.even_pace)}>
            Use {q.even_pace} a day
          </button>
        )}
      </p>
      <p className="mt-1 tabular-nums">
        With these settings, scans can still send <span className="text-zinc-900 dark:text-zinc-100">{leftToday}</span> request{leftToday === 1 ? "" : "s"} today{on ? "" : " (no daily limit)"}.
      </p>
    </div>
  );
}

function JSearchFields({ v, set, health, calls }: { v: SourcesSettings; set: (v: SourcesSettings) => void; health: SourceOut | null; calls: ApiCallOut[] | null }) {
  const failing = !!health?.last_error && (!health.last_success_at || (health.last_error_at ?? "") > health.last_success_at);
  return (
    <>
      <div className="flex items-start justify-between gap-4 rounded-md border border-zinc-200 px-3 py-3 dark:border-zinc-800">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-sm text-zinc-900 dark:text-zinc-100">
            JSearch <span className="text-xs text-zinc-500">Google for Jobs: LinkedIn, Naukri, Indeed, company sites</span>
            {health && !health.configured && <Badge tone="amber">API key missing</Badge>}
            <a href="https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-[11px] text-zinc-400 hover:text-violet-700 hover:underline dark:hover:text-violet-300">
              plan <ExternalLink className="size-3" />
            </a>
          </p>
          <p className="mt-0.5 text-xs text-zinc-500">
            {health?.last_success_at ? `Last success ${timeAgo(health.last_success_at)}` : "Never called"}
            {health ? ` · ${health.active_jobs.toLocaleString()} active jobs` : ""}
          </p>
          {health?.setup_hint && <p className="mt-0.5 text-xs text-amber-700 dark:text-amber-400">{health.setup_hint}</p>}
          {failing && <p className="mt-0.5 truncate text-xs text-rose-600/80 dark:text-rose-400/80" title={health?.last_error ?? undefined}>{timeAgo(health?.last_error_at)}: {health?.last_error}</p>}
        </div>
        <Toggle checked={v.enabled} onChange={(enabled) => set({ ...v, enabled })} label={`JSearch ${v.enabled ? "on" : "off"}`} />
      </div>

      <Field label="Key provider" hint="Where your JSEARCH_API_KEY comes from. OpenWeb Ninja keys also let the app read your plan's usage (Admin → JSearch analytics).">
        <Segmented
          value={v.provider}
          onChange={(provider) => set({ ...v, provider })}
          options={[
            { value: "openwebninja", label: "OpenWeb Ninja" },
            { value: "rapidapi", label: "RapidAPI" },
          ]}
        />
      </Field>

      <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-400">Request budget (1 request = up to 10 jobs)</h3>
      <div className="grid gap-5 sm:grid-cols-3">
        <Field label="Requests per month" htmlFor="j-limit" hint="Hard stop for the billing period. Free plan: 200.">
          <NumInput id="j-limit" min={0} step={10} value={v.monthly_limit} onChange={(n) => n != null && set({ ...v, monthly_limit: Math.round(n) })} />
        </Field>
        <Field label="Requests per scan" htmlFor="j-scan" hint="1 = each scan fetches one page of up to 10 jobs.">
          <NumInput id="j-scan" min={0} step={1} value={v.max_per_scan} onChange={(n) => n != null && set({ ...v, max_per_scan: Math.round(n) })} />
        </Field>
      </div>
      <p className="text-xs text-zinc-500">
        Up to {v.max_per_scan * 10} jobs per scan · {v.daily_limit_on ? `${v.daily_limit} requests (${v.daily_limit * 10} jobs) a day at most` : "no daily limit"} · {v.monthly_limit} requests ({v.monthly_limit * 10} jobs) a month at most.
      </p>
      <div className="grid gap-5 sm:grid-cols-3">
        <Field label="Reserve" htmlFor="j-reserve" hint="Kept back from scans for tests.">
          <NumInput id="j-reserve" min={0} step={1} value={v.reserve} onChange={(n) => n != null && set({ ...v, reserve: Math.round(n) })} />
        </Field>
      </div>
      <SwitchRow
        label="Limit requests per day"
        hint="On: scans stop after Requests per day each day (UTC), starting fresh every day however much was spent before. Off: scans may use everything left this period (the reserve stays kept back)."
        checked={v.daily_limit_on}
        onChange={(daily_limit_on) => set({ ...v, daily_limit_on, daily_limit: daily_limit_on && v.daily_limit < 1 ? 1 : v.daily_limit })}
      />
      {v.daily_limit_on && (
        <Field label="Requests per day" htmlFor="j-day" className="max-w-xs">
          <NumInput id="j-day" min={1} step={1} value={v.daily_limit} onChange={(n) => n != null && set({ ...v, daily_limit: Math.max(1, Math.round(n)) })} />
        </Field>
      )}
      <BudgetStatus on={v.daily_limit_on} perDay={v.daily_limit} onUsePace={(n) => set({ ...v, daily_limit_on: true, daily_limit: n })} />
      <Field label="Shortest posting window for repeat searches" hint="A search that ran recently asks only for newer jobs, but never for a narrower window than this (“today” returned 0–1 jobs).">
        <Segmented
          value={v.min_date_posted}
          onChange={(min_date_posted) => set({ ...v, min_date_posted })}
          options={[
            { value: "today", label: "Today" },
            { value: "3days", label: "3 days" },
            { value: "week", label: "Week" },
            { value: "month", label: "Month" },
          ]}
        />
      </Field>
      <JSearchTest configured={!!health?.configured} />

      <MoreOptions label="Pages, back-off, country, publishers">
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Second page" hint="Smart: only when page 1 was full (10 jobs) and brought enough new ones.">
            <Segmented
              value={v.pages_policy}
              onChange={(pages_policy) => set({ ...v, pages_policy })}
              options={[
                { value: "smart", label: "Smart" },
                { value: "single", label: "Never" },
              ]}
            />
          </Field>
          <Field label="New jobs on page 1 to earn page 2" htmlFor="j-p2">
            <NumInput id="j-p2" min={1} max={10} step={1} value={v.page2_min_new} onChange={(n) => n != null && set({ ...v, page2_min_new: Math.round(n) })} className="w-24" />
          </Field>
          <Field label="Back off after empty runs" htmlFor="j-bo" hint="A search with nothing new this many times in a row runs every 3 days, then weekly.">
            <NumInput id="j-bo" min={1} step={1} value={v.backoff_after_empty} onChange={(n) => n != null && set({ ...v, backoff_after_empty: Math.round(n) })} className="w-24" />
          </Field>
          <Field label="Request timeout (s)" htmlFor="j-to" hint="Never retried: a retry would spend quota.">
            <NumInput id="j-to" min={5} step={5} value={v.timeout_seconds} onChange={(n) => n != null && set({ ...v, timeout_seconds: n })} className="w-24" />
          </Field>
          <Field label="Search API country" htmlFor="j-cc" hint="Searched when Search criteria has no Locations. ISO code, e.g. IN.">
            <Input id="j-cc" value={v.api_country} maxLength={2} onChange={(e) => set({ ...v, api_country: e.target.value.toUpperCase() })} className="w-20 font-mono uppercase" />
          </Field>
        </div>
        <Field label="Leave out these job sites" hint="Publisher names as JSearch shows them (e.g. BeeBe, Dice). Sent as exclude_job_publishers.">
          <ChipInput value={v.excluded_publishers} onChange={(excluded_publishers) => set({ ...v, excluded_publishers })} placeholder="e.g. BeeBe — press Enter" />
        </Field>
      </MoreOptions>

      <h3 className="border-t border-zinc-100 pt-5 text-xs font-medium uppercase tracking-wide text-zinc-400 dark:border-zinc-800">Recent requests</h3>
      {!calls ? (
        <Skeleton className="h-16" />
      ) : calls.length === 0 ? (
        <p className="text-sm text-zinc-500">No requests yet.</p>
      ) : (
        <div className="max-h-72 overflow-auto rounded-md border border-zinc-200 dark:border-zinc-800">
          <table className="w-full min-w-[34rem] text-left text-xs">
            <thead className="sticky top-0 bg-white dark:bg-zinc-950">
              <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">Search</th>
                <th className="px-3 py-2 font-medium">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {calls.map((c) => (
                <tr key={c.id}>
                  <td className="px-3 py-2 text-zinc-500">{timeAgo(c.at)}</td>
                  <td className="px-3 py-2 text-zinc-800 dark:text-zinc-200">
                    {c.query ?? "—"}
                    {c.page > 1 && <span className="text-zinc-400"> · page {c.page}</span>}
                    {c.purpose !== "scan" && <span className="text-zinc-400"> · {c.purpose}</span>}
                  </td>
                  <td className="px-3 py-2 text-zinc-500">
                    {c.status === "ok" ? `${c.results} jobs · ${c.new_jobs} new · ${c.relevant_jobs} relevant` : c.status === "sending" ? "sent (no answer recorded)" : <span className="text-rose-600/80 dark:text-rose-400/80">{c.error ?? "failed"}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ── Schedule + limits ──────────────────────────────────────────────────────────

function ScheduleFields({ v, set }: { v: ScheduleSettings; set: (v: ScheduleSettings) => void }) {
  return (
    <>
      <SwitchRow label="Auto-scan" hint="The agent scans your sources on the schedule below, by itself." checked={v.autoscan} onChange={(autoscan) => set({ ...v, autoscan })} />
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Time" htmlFor="sch-time">
          <Input id="sch-time" type="time" value={v.time} onChange={(e) => e.target.value && set({ ...v, time: e.target.value })} className="w-32 tabular-nums" />
        </Field>
        <Field label="Time zone" htmlFor="sch-tz" hint="IANA name, e.g. Asia/Kolkata.">
          <Input id="sch-tz" list="tz-list" value={v.timezone} onChange={(e) => set({ ...v, timezone: e.target.value })} spellCheck={false} />
          <datalist id="tz-list">
            {TIMEZONES.map((z) => (
              <option key={z} value={z} />
            ))}
          </datalist>
        </Field>
        <Field label="Repeat">
          <Segmented
            value={String(v.every_hours) as "12" | "24"}
            onChange={(x) => set({ ...v, every_hours: x === "12" ? 12 : 24 })}
            options={[
              { value: "24", label: "Daily" },
              { value: "12", label: "Every 12 h" },
            ]}
          />
        </Field>
        <Field label="Ignore postings older than (days)" htmlFor="sch-rec">
          <NumInput id="sch-rec" min={1} step={1} value={v.recency_days} onChange={(n) => n != null && set({ ...v, recency_days: Math.round(n) })} className="w-32" />
        </Field>
      </div>
    </>
  );
}

const LIMIT_FIELDS: { key: keyof LimitsSettings; label: string; hint: string }[] = [
  { key: "keep_discarded_days", label: "Delete discarded jobs after (days)", hint: "Only jobs you discarded are ever deleted; they never come back." },
  { key: "expire_after_days", label: "Label as expired after (days)", hint: "Since it was posted (or found). A label only: nothing is deleted for being old." },
  { key: "raw_payload_days", label: "Keep raw source data (days)", hint: "The original record from JSearch." },
  { key: "repost_window_days", label: "Repost window (days)", hint: "A job reappearing within this window is treated as the same job." },
];

function LimitsFields({ v, set }: { v: LimitsSettings; set: (v: LimitsSettings) => void }) {
  return (
    <div className="grid gap-5 sm:grid-cols-2">
      {LIMIT_FIELDS.map((f) => (
        <Field key={f.key} label={f.label} htmlFor={`l-${f.key}`} hint={f.hint}>
          <NumInput id={`l-${f.key}`} min={0} step={1} value={v[f.key]} onChange={(n) => n != null && set({ ...v, [f.key]: Math.round(n) })} className="w-32" />
        </Field>
      ))}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function AdminSettings() {
  const toast = useToast();
  const location = useLocation();
  const [saved, setSaved] = useState<AdminSettingsOut | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [changedOnDisk, setChangedOnDisk] = useState(false);
  const sources = useResource(api.listSources);
  const calls = useResource(() => api.listApiCalls(50));

  const changed = saved && draft ? SECTIONS.filter((s) => !same(saved.settings[s.id], draft[s.id])) : [];
  const dirty = changed.length > 0;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const versionRef = useRef<string | null>(null);

  /** Take the server's state; the draft follows unless you have unsaved edits. */
  const take = useCallback((out: AdminSettingsOut, force = false) => {
    versionRef.current = out.version;
    setSaved(out);
    setChangedOnDisk(false);
    if (force || !dirtyRef.current) setDraft(out.settings);
  }, []);

  const load = useCallback(
    async (force = false) => {
      try {
        const out = await api.getAdminSettings();
        setLoadError(null);
        if (versionRef.current === null || force) take(out, true);
        else if (out.version !== versionRef.current) {
          if (dirtyRef.current) setChangedOnDisk(true);
          else take(out);
        }
      } catch (e) {
        setLoadError(errorMessage(e));
      }
    },
    [take],
  );

  // First load, then watch config.toml: hand edits of the file show up here within seconds.
  useEffect(() => {
    void load(true);
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, POLL_MS);
    return () => window.clearInterval(t);
  }, [load]);

  useEffect(() => {
    if (!draft || !location.hash) return;
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!draft, location.hash]);

  // Don't lose unsaved edits on tab close.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const save = async () => {
    if (!draft || !saved) return;
    setSaving(true);
    const heavy = changed.some((s) => s.id === "models" || s.id === "matching");
    try {
      const out = await api.saveAdminSettings(draft, saved.version);
      take(out, true);
      toast.success("Saved to config.toml", heavy ? "Jobs are re-scored in the background; re-embedding runs only if the model or metric changed." : "In effect now.");
      if (changed.some((s) => s.id === "sources")) {
        void sources.reload();
        void calls.reload();
      }
    } catch (e) {
      const msg = errorMessage(e);
      if (msg.includes("changed elsewhere")) setChangedOnDisk(true);
      toast.error("Couldn't save", msg);
    } finally {
      setSaving(false);
    }
  };

  function set<K extends AdminSection>(k: K, v: Settings[K]) {
    setDraft((d) => (d ? { ...d, [k]: v } : d));
  }

  const sectionError = (id: AdminSection) =>
    saved?.section_errors[id] ? <p className="text-xs text-rose-600/80 dark:text-rose-400/80">config.toml has an invalid value here, so defaults are shown: {saved.section_errors[id]}</p> : null;

  return (
    <div className="pb-20">
      <PageHeader
        title="Admin settings"
        subtitle={
          <>
            The system's tuning. Everything here is <span className="font-mono text-[12px]">settings/config.toml</span>: saving rewrites only what you changed (comments kept), and edits made in the file appear here within seconds.
          </>
        }
      />

      {loadError && !saved && (
        <div className="mb-6">
          <ErrorBanner message={loadError} onRetry={() => void load(true)} />
        </div>
      )}
      {saved?.file_error && (
        <div className="mb-6">
          <ErrorBanner message={`config.toml can't be read right now, so the last good values are in use: ${saved.file_error}`} />
        </div>
      )}
      {changedOnDisk && (
        <div className="mb-6 flex flex-wrap items-center gap-3 rounded-md border border-amber-300/60 bg-amber-50/60 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          <FileCog className="size-4 shrink-0" />
          <span className="flex-1">config.toml was changed outside this page. Reload to see it (your unsaved edits here are dropped).</span>
          <Button size="sm" icon={<RefreshCw className="size-3.5" />} onClick={() => void load(true)}>
            Reload
          </Button>
        </div>
      )}

      {!draft && !loadError && (
        <div className="space-y-4">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      )}

      {draft && saved && (
        <div className="grid gap-8 lg:grid-cols-[9.5rem_minmax(0,1fr)]">
          <SectionNav sections={SECTIONS} dirty={(id) => changed.some((c) => c.id === id)} />

          <div className="min-w-0 space-y-6">
            <Section id="models" title="Models" description="Which AI models the app calls, and how. API keys stay in .env." dirty={!same(saved.settings.models, draft.models)}>
              {sectionError("models")}
              <ModelsFields v={draft.models} saved={saved.settings.models} set={(v) => set("models", v)} env={saved.env_overrides} />
            </Section>

            <Section id="matching" title="Matching" description="How jobs are compared with your roles and memory cards." dirty={!same(saved.settings.matching, draft.matching)}>
              {sectionError("matching")}
              <MatchingFields v={draft.matching} saved={saved.settings.matching} set={(v) => set("matching", v)} />
            </Section>

            <Section id="sources" title="JSearch" description="The only job source. Its free plan has 200 requests a month; these rules decide how they're spent. What each scan sends is on Search Settings → Search plan." dirty={!same(saved.settings.sources, draft.sources)}>
              {sectionError("sources")}
              {sources.error && <ErrorBanner message={sources.error} onRetry={sources.reload} />}
              <JSearchFields v={draft.sources} set={(v) => set("sources", v)} health={sources.data?.find((x) => x.name === "jsearch") ?? null} calls={calls.data ?? null} />
            </Section>

            <Section id="schedule" title="Schedule" description="When the agent runs a scan by itself." dirty={!same(saved.settings.schedule, draft.schedule)}>
              {sectionError("schedule")}
              <ScheduleFields v={draft.schedule} set={(v) => set("schedule", v)} />
            </Section>

            <Section id="limits" title="Limits & retention" description="Jobs stay until you discard them (or the agent applies). Only discarded jobs are deleted." dirty={!same(saved.settings.limits, draft.limits)}>
              {sectionError("limits")}
              <LimitsFields v={draft.limits} set={(v) => set("limits", v)} />
            </Section>

            <p className="text-[11px] text-zinc-400">
              File: <span className="font-mono">{saved.file}</span>
            </p>
          </div>
        </div>
      )}

      {dirty && (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-zinc-200 bg-white/95 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95">
          <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-4 py-3 sm:px-8">
            <p className="flex-1 text-sm text-zinc-700 dark:text-zinc-300">
              Unsaved changes in <span className="font-medium">{changed.map((s) => LABEL[s.id]).join(", ")}</span>
            </p>
            <Button size="sm" variant="ghost" disabled={saving} onClick={() => saved && setDraft(saved.settings)}>
              Discard
            </Button>
            <Button size="sm" variant="primary" loading={saving} onClick={() => void save()}>
              Save &amp; apply
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
