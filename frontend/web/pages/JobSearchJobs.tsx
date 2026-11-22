import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, Check, ChevronDown, ChevronRight, Plus, Radar, RotateCcw, Search, X } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import type { ApplyKind, Category, JobCard, JobDecision, JobsOut, JobsView, Workplace } from "../lib/types";
import { cx, useResource } from "../lib/util";
import { Badge, Button, Card, EmptyState, ErrorBanner, Input, PageHeader, Skeleton } from "../components/ui";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { FilterChips, MiniBar } from "../components/jobs/ToggleChips";
import { JobDetailPanel } from "../components/jobs/JobDetailPanel";
import { AddRoleModal } from "../components/jobs/AddRole";
import { APPLY_KIND_LABEL, CATEGORY_LABEL, WORKPLACE_LABEL, applyRoute, foundAgo, formatPay, pct } from "../components/jobs/format";
import { Select } from "../components/settings/form";

const CATEGORY_OPTS = (Object.keys(CATEGORY_LABEL) as Category[]).map((v) => ({ value: v, label: CATEGORY_LABEL[v] }));
const WORKPLACE_OPTS = (Object.keys(WORKPLACE_LABEL) as Workplace[]).map((v) => ({ value: v, label: WORKPLACE_LABEL[v] }));
const YEARS_OPTS = [0, 1, 2, 3, 5, 8];
const YEARS_KEY = "jobs.maxYears";
const APPLY_OPTS = (Object.keys(APPLY_KIND_LABEL) as ApplyKind[]).map((v) => ({ value: v, label: APPLY_KIND_LABEL[v] }));

// ── Date found ────────────────────────────────────────────────────────────────

const TZ = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return undefined;
  }
})();
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoDay(d);
};
const dayLabel = (iso: string) => {
  const label = new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  return iso === daysAgo(0) ? `Today, ${label}` : iso === daysAgo(1) ? `Yesterday, ${label}` : label;
};

/** "" any · today · yesterday · 7 / 30 (last N days) · day:YYYY-MM-DD · custom */
type DateSel = string;

function dateRange(sel: DateSel, custom: { from: string; to: string }): { from?: string; to?: string } {
  if (sel === "today") return { from: daysAgo(0), to: daysAgo(0) };
  if (sel === "yesterday") return { from: daysAgo(1), to: daysAgo(1) };
  if (sel === "7") return { from: daysAgo(6) };
  if (sel === "30") return { from: daysAgo(29) };
  if (sel.startsWith("day:")) return { from: sel.slice(4), to: sel.slice(4) };
  if (sel === "custom") return { from: custom.from || undefined, to: custom.to || undefined };
  return {};
}

function savedMaxYears(): number | null {
  try {
    const v = localStorage.getItem(YEARS_KEY);
    return v == null || v === "" ? null : Number(v);
  } catch {
    return null;
  }
}

const VIEWS: { id: JobsView; label: string; count: (c: Record<string, number>) => number; hint: string }[] = [
  { id: "matches", label: "Matches", count: (c) => (c.fits ?? 0) + (c.other ?? 0), hint: "Relevant jobs you haven't decided on yet." },
  { id: "selected", label: "Selected", count: (c) => c.selected ?? 0, hint: "Jobs you picked. The agent will apply to these (later phase)." },
  { id: "applied", label: "Applied", count: (c) => c.applied ?? 0, hint: "Jobs marked as applied." },
  { id: "discarded", label: "Discarded", count: (c) => c.discarded ?? 0, hint: "Deleted after a few days (Admin → Limits); they never come back. Restore one to undo." },
  { id: "not_relevant", label: "Not relevant", count: (c) => c.not_relevant ?? 0, hint: "Returned by JSearch, but the title didn't match your roles. Add a title to your roles if it fits you." },
  { id: "excluded", label: "Excluded", count: (c) => c.excluded ?? 0, hint: "Jobs your criteria excluded before 2026-11-20 (criteria only shape the scan now; shown only while any remain)." },
];

const DECISION_LABEL: Record<JobDecision, string> = { selected: "Selected", discarded: "Discarded", applied: "Applied" };

/** The job's location, highlighted against the place you searched (location never excludes a job). */
function JobPlace({ job }: { job: JobCard }) {
  const where = job.searched_place?.split(",")[0].trim();
  if (job.place_check === "elsewhere")
    return (
      <span className="font-medium text-amber-700 dark:text-amber-400" title={`You searched ${job.searched_place}`}>
        {job.location_text} <span className="font-normal">(not {where})</span>
      </span>
    );
  if (job.place_check === "match")
    return (
      <span className="font-medium text-zinc-800 dark:text-zinc-200" title={`In the place you searched: ${job.searched_place}`}>
        {job.location_text}
      </span>
    );
  if (job.place_check === "unknown" && job.searched_place?.includes(","))
    return (
      <span title={`You searched ${job.searched_place}; the posting doesn't say where in the country`}>
        {job.location_text} <span className="text-zinc-400">(area not stated)</span>
      </span>
    );
  return <span>{job.location_text}</span>;
}

function JobRow({ job, view, checked, onCheck, onOpen, onDecide, onAddTitle, onMoveToMatches }: {
  job: JobCard;
  view: JobsView;
  checked: boolean;
  onCheck: (v: boolean) => void;
  onOpen: () => void;
  onDecide: (d: JobDecision | null) => void;
  onAddTitle: () => void;
  onMoveToMatches: () => void;
}) {
  const pay = formatPay(job);
  const cov = job.coverage;
  const undecided = !job.decision;
  const route = applyRoute(job.apply_route);
  return (
    <li className={cx("flex items-start gap-3 px-4 py-3.5", checked && "bg-violet-50/40 dark:bg-violet-500/5")}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onCheck(e.target.checked)}
        aria-label={`Choose ${job.title}`}
        className="mt-1 size-4 shrink-0 accent-violet-600"
      />
      <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left focus-visible:outline-none">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
          <div className="min-w-0">
            <p className="text-sm font-medium text-zinc-900 hover:text-violet-700 dark:text-zinc-100 dark:hover:text-violet-300">
              {job.title}
              {job.expired && <span className="ml-2 text-[11px] font-normal text-zinc-400">expired</span>}
            </p>
            <p className="mt-0.5 truncate text-xs text-zinc-500 dark:text-zinc-400">
              {job.company_name || "Unknown company"}
              {job.location_text && (
                <>
                  {" · "}
                  <JobPlace job={job} />
                </>
              )}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-4 text-xs text-zinc-500 tabular-nums dark:text-zinc-400">
            {job.role_score != null && (
              <span title={job.role_match ? `Title vs your role: ${job.role_match}` : "Title match"}>{pct(job.role_score)} {job.role_match ?? "role"}</span>
            )}
            {job.relevance != null && (
              <span title="Job text vs that role's context (Memory ▾ Role contexts). Matches are ranked by this.">{pct(job.relevance)} context</span>
            )}
            {cov && cov.must_total > 0 && (
              <span className="flex items-center gap-1.5" title={cov.fit != null ? `${cov.fit}% fit` : undefined}>
                {cov.must_met}/{cov.must_total} must-haves
                {cov.fit != null && <MiniBar value={cov.fit} />}
              </span>
            )}
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {job.category && <Badge>{CATEGORY_LABEL[job.category]}</Badge>}
          {job.workplace_type && <Badge>{WORKPLACE_LABEL[job.workplace_type]}</Badge>}
          {route && <Badge tone={route.kind === "form" ? "green" : "neutral"}>{route.label}</Badge>}
          {job.min_years_experience != null && <Badge>{job.min_years_experience === 0 ? "No experience asked" : `${job.min_years_experience}+ yrs asked`}</Badge>}
          {job.country_codes.length > 0 && <Badge>{job.country_codes.join(", ")}</Badge>}
          {pay && <Badge tone={job.compensation_type === "unpaid" ? "neutral" : "accent"}>{pay}</Badge>}
          <span className="text-[11px] text-zinc-400" title={`Found ${new Date(job.first_seen_at).toLocaleString()}`}>
            found {foundAgo(job.first_seen_at)}
          </span>
        </div>
        {(view === "not_relevant" || view === "excluded") && job.status_reason && (
          <p className="mt-1.5 text-[11px] text-zinc-500">{job.status_reason}</p>
        )}
        {job.relevance_override && (
          <p className="mt-1.5 text-[11px] text-zinc-500">{job.relevance_override === "relevant" ? "You moved this to your matches" : "You marked this not relevant"}</p>
        )}
        {view === "matches" && !job.fits_preset && job.preset_misses.length > 0 && (
          <p className="mt-1.5 text-[11px] text-zinc-400">Outside preset: {job.preset_misses.join(" · ")}</p>
        )}
      </button>
      <div className="flex shrink-0 flex-col items-end gap-1 sm:flex-row sm:items-center">
        {(view === "not_relevant" || view === "excluded") && (
          <>
            <Button size="sm" icon={<ArrowUpRight className="size-3.5" />} onClick={onMoveToMatches} title="It is relevant: put it in your Matches (your call beats the checks)">
              Move to matches
            </Button>
            <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={onAddTitle} title="Add this job's title to your roles">
              Add title
            </Button>
          </>
        )}
        {undecided && (
          <>
            <Button size="sm" icon={<Check className="size-3.5" />} onClick={() => onDecide("selected")}>
              Select
            </Button>
            <Button size="sm" variant="ghost" icon={<X className="size-3.5" />} onClick={() => onDecide("discarded")}>
              Discard
            </Button>
          </>
        )}
        {job.decision === "selected" && (
          <>
            <Button size="sm" onClick={() => onDecide("applied")}>Mark applied</Button>
            <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} onClick={() => onDecide(null)}>
              Unselect
            </Button>
          </>
        )}
        {(job.decision === "discarded" || job.decision === "applied") && (
          <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} onClick={() => onDecide(null)}>
            {job.decision === "discarded" ? "Restore" : "Undo"}
          </Button>
        )}
      </div>
    </li>
  );
}

export default function JobSearchJobs() {
  const toast = useToast();
  const [view, setView] = useState<JobsView>("matches");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<Category | null>(null);
  const [workplace, setWorkplace] = useState<Workplace | null>(null);
  const [maxYears, setMaxYears] = useState<number | null>(savedMaxYears);
  const [applyKind, setApplyKind] = useState<ApplyKind | null>(null);
  const [dateSel, setDateSel] = useState<DateSel>("");
  const [custom, setCustom] = useState({ from: "", to: "" });
  const range = dateRange(dateSel, custom);
  const [otherOpen, setOtherOpen] = useState(true);
  const [openId, setOpenId] = useState<number | null>(null);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [confirmRest, setConfirmRest] = useState(false);
  const [addTitle, setAddTitle] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setQuery(q.trim()), 300);
    return () => window.clearTimeout(t);
  }, [q]);

  const { data, error, loading, reload } = useResource<JobsOut>(() =>
    api.listJobs({
      q: query || undefined,
      category: category ?? undefined,
      workplace: workplace ?? undefined,
      view,
      max_years: view === "matches" && maxYears != null ? maxYears : undefined,
      apply: applyKind ?? undefined,
      found_from: range.from,
      found_to: range.to,
      tz: TZ,
    }),
  );

  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    setChecked(new Set());
    void reload();
  }, [query, category, workplace, view, maxYears, applyKind, range.from, range.to, reload]);

  useEffect(() => {
    try {
      localStorage.setItem(YEARS_KEY, maxYears == null ? "" : String(maxYears));
    } catch {
      /* private window: not remembered */
    }
  }, [maxYears]);

  const shown: JobCard[] = useMemo(() => (data ? (view === "matches" ? [...data.fits, ...data.other] : data.items) : []), [data, view]);
  const filtered = !!(query || category || workplace || applyKind || range.from || range.to || (view === "matches" && maxYears != null));
  // Days with jobs in this tab; a picked day stays in the list even when other filters hide it.
  const days = useMemo(() => {
    const list = data?.days ?? [];
    const picked = dateSel.startsWith("day:") ? dateSel.slice(4) : null;
    return picked && !list.some((d) => d.date === picked) ? [{ date: picked, count: 0 }, ...list] : list;
  }, [data, dateSel]);
  const counts = data?.counts ?? {};
  const current = VIEWS.find((v) => v.id === view)!;

  const toggle = (id: number, on: boolean) =>
    setChecked((s) => {
      const n = new Set(s);
      if (on) n.add(id);
      else n.delete(id);
      return n;
    });

  const decide = async (ids: number[], decision: JobDecision | null, message?: string) => {
    if (!ids.length) return;
    setBusy(true);
    try {
      await api.decideJobs(ids, decision);
      toast.success(message ?? (decision ? `${ids.length} job${ids.length === 1 ? "" : "s"} ${DECISION_LABEL[decision].toLowerCase()}` : `${ids.length} job${ids.length === 1 ? "" : "s"} back to undecided`));
      setChecked(new Set());
      await reload();
    } catch (e) {
      toast.error("Couldn't update", errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const moveToMatches = async (j: JobCard) => {
    setBusy(true);
    try {
      await api.setRelevance(j.id, "relevant");
      toast.success("Moved to your matches", "Your call sticks: re-checks won't move it back.");
      await reload();
    } catch (e) {
      toast.error("Couldn't move the job", errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const selectAndDiscardRest = async () => {
    setConfirmRest(false);
    const keep = [...checked];
    const rest = shown.filter((j) => !j.decision && !checked.has(j.id)).map((j) => j.id);
    setBusy(true);
    try {
      if (keep.length) await api.decideJobs(keep, "selected");
      if (rest.length) await api.decideJobs(rest, "discarded");
      toast.success(`${keep.length} selected · ${rest.length} discarded`);
      setChecked(new Set());
      await reload();
    } catch (e) {
      toast.error("Couldn't update", errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const allChecked = shown.length > 0 && shown.every((j) => checked.has(j.id));
  const restCount = shown.filter((j) => !j.decision && !checked.has(j.id)).length;

  const row = (j: JobCard) => (
    <JobRow
      key={j.id}
      job={j}
      view={view}
      checked={checked.has(j.id)}
      onCheck={(v) => toggle(j.id, v)}
      onOpen={() => setOpenId(j.id)}
      onDecide={(d) => void decide([j.id], d)}
      onAddTitle={() => setAddTitle(j.title)}
      onMoveToMatches={() => void moveToMatches(j)}
    />
  );

  return (
    <div className="pb-20">
      <PageHeader title="Jobs" subtitle={current.hint} />

      <div className="mb-5 flex flex-wrap gap-1 border-b border-zinc-200 dark:border-zinc-800" role="tablist" aria-label="Job lists">
        {VIEWS.filter((v) => v.id !== "excluded" || v.count(counts) > 0 || view === "excluded").map((v) => (
          <button
            key={v.id}
            type="button"
            role="tab"
            aria-selected={view === v.id}
            onClick={() => setView(v.id)}
            className={cx(
              "-mb-px border-b-2 px-3 py-2 text-sm transition-colors",
              view === v.id ? "border-violet-600 text-zinc-900 dark:border-violet-400 dark:text-zinc-50" : "border-transparent text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200",
            )}
          >
            {v.label} <span className="text-xs text-zinc-400 tabular-nums">{data ? v.count(counts) : ""}</span>
          </button>
        ))}
      </div>

      <div className="mb-6 space-y-3">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, company, location…" aria-label="Search jobs" className="pl-9" />
        </div>
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:gap-6">
          <FilterChips label="Job type" value={category} onChange={setCategory} options={CATEGORY_OPTS} />
          <FilterChips label="Workplace" value={workplace} onChange={setWorkplace} options={WORKPLACE_OPTS} />
          <FilterChips label="Apply via" value={applyKind} onChange={setApplyKind} options={APPLY_OPTS} />
          <label className="flex items-center gap-2 text-xs text-zinc-500" title="The day a scan first found the job (your timezone).">
            Date found
            <Select value={dateSel} onChange={(e) => setDateSel(e.target.value)} className="w-auto py-1 text-xs">
              <option value="">Any day</option>
              <option value="today">Today</option>
              <option value="yesterday">Yesterday</option>
              <option value="7">Last 7 days</option>
              <option value="30">Last 30 days</option>
              <option value="custom">Custom range…</option>
              {days.length > 0 && (
                <optgroup label="Days with jobs in this tab">
                  {days.slice(0, 60).map((d) => (
                    <option key={d.date} value={`day:${d.date}`}>
                      {dayLabel(d.date)} · {d.count} job{d.count === 1 ? "" : "s"}
                    </option>
                  ))}
                </optgroup>
              )}
            </Select>
          </label>
          {dateSel === "custom" && (
            <span className="flex items-center gap-1.5 text-xs text-zinc-500">
              <Input type="date" aria-label="Found from" value={custom.from} max={custom.to || undefined} onChange={(e) => setCustom((c) => ({ ...c, from: e.target.value }))} className="h-8 w-auto py-1 text-xs" />
              to
              <Input type="date" aria-label="Found to" value={custom.to} min={custom.from || undefined} onChange={(e) => setCustom((c) => ({ ...c, to: e.target.value }))} className="h-8 w-auto py-1 text-xs" />
            </span>
          )}
          {view === "matches" && (
            <label className="flex items-center gap-2 text-xs text-zinc-500" title="Jobs that don't say how many years they ask for always stay.">
              Experience asked
              <Select value={maxYears == null ? "" : String(maxYears)} onChange={(e) => setMaxYears(e.target.value === "" ? null : Number(e.target.value))} className="w-auto py-1 text-xs">
                <option value="">Any</option>
                {YEARS_OPTS.map((y) => (
                  <option key={y} value={y}>
                    {y === 0 ? "None (fresher)" : `Up to ${y} year${y === 1 ? "" : "s"}`}
                  </option>
                ))}
              </Select>
            </label>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} onRetry={reload} />
        </div>
      )}

      {loading && !data && (
        <div className="space-y-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      )}

      {data && shown.length === 0 && (
        <Card>
          {filtered ? (
            <EmptyState icon={<Search className="size-5" />} title="No jobs match" body="Try a different search or clear the filters." />
          ) : view === "matches" ? (
            <EmptyState
              icon={<Radar className="size-5" />}
              title="No undecided matches"
              body="Run a scan to gather jobs. Relevant ones land here; select the ones you want the agent to apply to and discard the rest."
              action={
                <Link to="/job-search">
                  <Button variant="primary">Go to Overview</Button>
                </Link>
              }
            />
          ) : (
            <EmptyState icon={<Search className="size-5" />} title={`Nothing in ${current.label.toLowerCase()}`} body={current.hint} />
          )}
        </Card>
      )}

      {data && shown.length > 0 && (
        <>
          <label className="mb-2 flex items-center gap-2 px-1 text-xs text-zinc-500">
            <input
              type="checkbox"
              checked={allChecked}
              onChange={(e) => setChecked(e.target.checked ? new Set(shown.map((j) => j.id)) : new Set())}
              className="size-4 accent-violet-600"
            />
            Choose all {shown.length}
          </label>
          {view === "matches" ? (
            <div className="space-y-8">
              <section>
                <h2 className="mb-3 text-xs font-semibold tracking-wider text-zinc-400 uppercase">
                  Fits your preset <span className="tabular-nums">({data.fits.length})</span>
                </h2>
                {data.fits.length ? (
                  <Card>
                    <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">{data.fits.map(row)}</ul>
                  </Card>
                ) : (
                  <p className="text-sm text-zinc-500">
                    Nothing fits your preset{filtered ? " with these filters" : ""}.{" "}
                    <Link to="/job-search/settings#preset" className="text-violet-700 hover:underline dark:text-violet-300">
                      Adjust the preset
                    </Link>
                  </p>
                )}
              </section>
              {data.other.length > 0 && (
                <section>
                  <button
                    type="button"
                    onClick={() => setOtherOpen((o) => !o)}
                    aria-expanded={otherOpen}
                    className="mb-3 flex items-center gap-1 text-xs font-semibold tracking-wider text-zinc-400 uppercase hover:text-zinc-600 dark:hover:text-zinc-300"
                  >
                    {otherOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                    Other relevant jobs <span className="tabular-nums">({data.other.length})</span>
                  </button>
                  {otherOpen && (
                    <Card>
                      <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">{data.other.map(row)}</ul>
                    </Card>
                  )}
                </section>
              )}
            </div>
          ) : (
            <Card>
              <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">{data.items.map(row)}</ul>
            </Card>
          )}
        </>
      )}

      {checked.size > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-zinc-200 bg-white/95 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95">
          <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-2 px-4 py-3 sm:px-8">
            <p className="flex-1 text-sm text-zinc-700 dark:text-zinc-300">{checked.size} chosen</p>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => setChecked(new Set())}>
              Clear
            </Button>
            {view === "selected" || view === "applied" || view === "discarded" ? (
              <>
                {view === "selected" && (
                  <Button size="sm" disabled={busy} onClick={() => void decide([...checked], "applied")}>
                    Mark applied
                  </Button>
                )}
                <Button size="sm" disabled={busy} onClick={() => void decide([...checked], null)}>
                  {view === "discarded" ? "Restore" : "Back to undecided"}
                </Button>
              </>
            ) : (
              <>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => void decide([...checked], "discarded")}>
                  Discard
                </Button>
                <Button size="sm" disabled={busy} onClick={() => void decide([...checked], "selected")}>
                  Select
                </Button>
                {view === "matches" && restCount > 0 && (
                  <Button size="sm" variant="primary" loading={busy} onClick={() => setConfirmRest(true)}>
                    Select these & discard the rest ({restCount})
                  </Button>
                )}
              </>
            )}
          </div>
        </div>
      )}

      <Modal
        open={confirmRest}
        onClose={() => setConfirmRest(false)}
        title={`Select ${checked.size} and discard ${restCount}?`}
        footer={
          <>
            <Button onClick={() => setConfirmRest(false)}>Cancel</Button>
            <Button variant="primary" onClick={() => void selectAndDiscardRest()}>
              Select & discard
            </Button>
          </>
        }
      >
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          The {checked.size} chosen job{checked.size === 1 ? "" : "s"} move to Selected (the agent's list). The other {restCount} undecided job{restCount === 1 ? "" : "s"} in this view{filtered ? " (with your current filters)" : ""} move to Discarded and are deleted after a few days. You can restore them until then.
        </p>
      </Modal>

      <AddRoleModal title={addTitle ?? ""} open={addTitle !== null} onClose={() => setAddTitle(null)} onAdded={() => window.setTimeout(() => void reload(), 1500)} />

      <JobDetailPanel jobId={openId} onClose={() => setOpenId(null)} onChanged={() => void reload()} />
    </div>
  );
}
