// Admin → Company finder (2026-11-23): what every company-finder run did. The finder runs by
// itself while the backend runs (one run after another while companies are waiting); it keeps a
// company only when its job board has jobs in India or remote jobs open to India.
import { Fragment, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Building2, ChevronDown, ChevronRight, Play } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import type { FinderBreakdownRow, FinderDashboardOut, FinderRunOut } from "../lib/types";
import { cx, timeAgo, useResource } from "../lib/util";
import { Badge, Button, Card, EmptyState, ErrorBanner, PageHeader, Skeleton, Spinner } from "../components/ui";
import { useToast } from "../components/Toast";
import { dateTime } from "../components/jobs/format";

const ORIGIN: Record<string, string> = { seed: "Seed list", yc: "YC list", crawl: "Web index" };
const HOW: Record<string, string> = { careers_page: "careers page", guessed: "name tried", crawl: "web index" };

/** Outcome of a check, in stack order (bottom first). Kept is the accent; the rest recede. */
const OUTCOMES = [
  { key: "kept", label: "Kept", swatch: "bg-violet-600 dark:bg-violet-400", fill: "fill-violet-600 dark:fill-violet-400" },
  { key: "no_india_jobs", label: "No jobs in India", swatch: "bg-zinc-400 dark:bg-zinc-500", fill: "fill-zinc-400 dark:fill-zinc-500" },
  { key: "no_board", label: "No board found", swatch: "bg-zinc-300 dark:bg-zinc-700", fill: "fill-zinc-300 dark:fill-zinc-700" },
  { key: "error", label: "Couldn't be read", swatch: "bg-amber-500 dark:bg-amber-400", fill: "fill-amber-500 dark:fill-amber-400" },
] as const;

const pct = (a: number, b: number) => (b ? `${Math.round((a / b) * 100)}%` : "—");
const n = (v: number | undefined | null) => (v ? v.toLocaleString() : "—");

function duration(s: number | null): string {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)} s`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

function SectionHead({ title, extra }: { title: string; extra?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-xs font-semibold tracking-wider text-zinc-400 uppercase">{title}</h2>
      {extra}
    </div>
  );
}

function Tile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-[11px] text-zinc-500 dark:text-zinc-400">{label}</p>
      <p className="mt-1 font-serif text-2xl text-zinc-900 tabular-nums dark:text-zinc-50">{value}</p>
      {hint && <p className="mt-0.5 text-[11px] text-zinc-400">{hint}</p>}
    </Card>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
      {OUTCOMES.map((o) => (
        <span key={o.key} className="inline-flex items-center gap-1.5">
          <span className={cx("size-2.5 rounded-sm", o.swatch)} />
          {o.label}
        </span>
      ))}
    </div>
  );
}

/** One stacked bar per run (oldest left): what its checks found. Hover a bar for its numbers. */
function RunsChart({ runs }: { runs: FinderRunOut[] }) {
  const rows = runs.filter((r) => (r.counts.checked ?? 0) > 0).slice(0, 40).reverse();
  if (!rows.length) return <EmptyState icon={<Building2 className="size-5" />} title="No checks yet" body="Each run's results appear here as soon as it has checked a company." />;
  const max = Math.max(1, ...rows.map((r) => r.counts.checked ?? 0));
  const W = 12;
  const H = 100;
  const gap = 3;
  return (
    <div className="flex gap-2">
      <div className="flex h-44 flex-col justify-between text-right text-[10px] text-zinc-400 tabular-nums">
        <span>{max}</span>
        <span>0</span>
      </div>
      <div className="min-w-0 flex-1">
        <svg viewBox={`0 0 ${rows.length * W} ${H}`} preserveAspectRatio="none" className="h-44 w-full border-b border-zinc-200 dark:border-zinc-800" role="img" aria-label={`Companies checked per run, last ${rows.length} runs`}>
          {rows.map((r, i) => {
            let y = H;
            return (
              <g key={r.id}>
                <title>
                  {`Run ${r.id} · ${dateTime(r.started_at)}\n${r.counts.checked ?? 0} checked: ${OUTCOMES.map((o) => `${r.counts[o.key] ?? 0} ${o.label.toLowerCase()}`).join(", ")}\n${r.india_jobs} jobs in India on the boards kept`}
                </title>
                <rect x={i * W} y={0} width={W} height={H} className="fill-transparent" />
                {OUTCOMES.map((o) => {
                  const v = r.counts[o.key] ?? 0;
                  if (!v) return null;
                  const h = (v / max) * H;
                  y -= h;
                  // A thin surface gap between segments keeps them apart.
                  return <rect key={o.key} x={i * W + gap / 2} y={y + 0.4} width={W - gap} height={Math.max(h - 0.8, 0.6)} className={o.fill} />;
                })}
              </g>
            );
          })}
        </svg>
        <div className="mt-1 flex justify-between text-[10px] text-zinc-400">
          <span>Run {rows[0].id}</span>
          <span>Run {rows[rows.length - 1].id}</span>
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ r }: { r: FinderRunOut }) {
  if (r.status === "running")
    return (
      <Badge tone="accent">
        <Spinner className="size-3" /> running
      </Badge>
    );
  if (r.status === "failed") return <Badge tone="red" title={r.error ?? undefined}>failed</Badge>;
  if (r.status === "interrupted") return <Badge tone="amber" title="The app restarted during this run; the companies it checked stay checked">interrupted</Badge>;
  return <Badge>done</Badge>;
}

function RunDetail({ r }: { r: FinderRunOut }) {
  const kinds = Object.entries(r.by_kind).sort((a, b) => b[1].checked - a[1].checked);
  return (
    <div className="grid gap-5 px-5 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
      <div className="space-y-3 text-xs text-zinc-600 dark:text-zinc-400">
        <p>
          <span className="text-zinc-400">Added to the waiting list:</span>{" "}
          {Object.entries(r.new_leads).filter(([, v]) => v).map(([k, v]) => `${v.toLocaleString()} from the ${ORIGIN[k] ?? k}`).join(" · ") || "nothing new"}
        </p>
        {(r.crawl.blocks ?? 0) > 0 && (
          <p>
            <span className="text-zinc-400">Web index:</span> {r.crawl.blocks} blocks of {(r.crawl.collections ?? []).join(", ")}
          </p>
        )}
        {r.crawl.error && <p className="text-amber-700 dark:text-amber-400">Web index stopped early: {r.crawl.error} (carried on next run)</p>}
        {r.error && <p className="text-rose-600 dark:text-rose-400">{r.error}</p>}
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
              <th className="py-1.5 pr-3 font-medium">Hiring system</th>
              <th className="py-1.5 pr-3 font-medium">Checked</th>
              <th className="py-1.5 pr-3 font-medium">Kept</th>
              <th className="py-1.5 font-medium">India jobs</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 tabular-nums dark:divide-zinc-800">
            {kinds.map(([k, c]) => (
              <tr key={k}>
                <td className="py-1.5 pr-3">{k === "none" ? "No board found" : k}</td>
                <td className="py-1.5 pr-3">{c.checked}</td>
                <td className="py-1.5 pr-3 text-zinc-900 dark:text-zinc-100">{c.kept || "—"}</td>
                <td className="py-1.5">{n(c.india_jobs)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-xs">
        <p className="mb-2 text-zinc-400">Companies kept ({r.kept.length}): every scan now reads their boards</p>
        {r.kept.length === 0 ? (
          <p className="text-zinc-500">None this run.</p>
        ) : (
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-left">
              <thead className="sticky top-0 bg-white dark:bg-zinc-950">
                <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
                  <th className="py-1.5 pr-3 font-medium">Company</th>
                  <th className="py-1.5 pr-3 font-medium">Board</th>
                  <th className="py-1.5 pr-3 font-medium">From</th>
                  <th className="py-1.5 font-medium">In India / matching your roles</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {[...r.kept]
                  .sort((a, b) => (b.matching_jobs ?? 0) - (a.matching_jobs ?? 0) || (b.india_jobs ?? 0) - (a.india_jobs ?? 0))
                  .map((k) => (
                    <tr key={`${k.kind}-${k.name}`}>
                      <td className="py-1.5 pr-3 text-zinc-900 dark:text-zinc-100">{k.name}</td>
                      <td className="py-1.5 pr-3 text-zinc-500">{k.kind}</td>
                      <td className="py-1.5 pr-3 text-zinc-500">
                        {ORIGIN[k.origin] ?? k.origin}
                        {k.how && k.how !== "crawl" ? ` · ${HOW[k.how] ?? k.how}` : ""}
                      </td>
                      <td className="py-1.5 text-zinc-500 tabular-nums">
                        {k.india_jobs ?? "—"} / {k.matching_jobs ?? "—"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function RunsTable({ runs }: { runs: FinderRunOut[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!runs.length) return <p className="px-5 pb-5 text-sm text-zinc-500">No runs yet. The first one starts within a minute of the app starting.</p>;
  return (
    <table className="w-full min-w-[52rem] text-left text-sm">
      <thead>
        <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
          {["Run", "Started", "Took", "New on the list", "Checked", "Kept", "No India jobs", "No board", "India jobs on kept boards", ""].map((h, i) => (
            <th key={i} className="px-3 py-2 font-medium first:pl-5">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-zinc-100 tabular-nums dark:divide-zinc-800">
        {runs.map((r) => {
          const isOpen = open === r.id;
          const added = Object.values(r.new_leads).reduce((a, b) => a + b, 0);
          return (
            <Fragment key={r.id}>
              <tr className="cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-900/50" onClick={() => setOpen(isOpen ? null : r.id)} aria-expanded={isOpen}>
                <td className="py-2 pr-3 pl-5 whitespace-nowrap text-zinc-500">
                  <span className="inline-flex items-center gap-1">
                    {isOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                    {r.id}
                  </span>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-zinc-500" title={dateTime(r.started_at)}>
                  {timeAgo(r.started_at)}
                  <span className="ml-1.5 text-[11px] text-zinc-400">{r.trigger === "manual" ? "by you" : "auto"}</span>
                </td>
                <td className="px-3 py-2 text-zinc-500">{duration(r.duration_seconds)}</td>
                <td className="px-3 py-2">{n(added)}</td>
                <td className="px-3 py-2">
                  {n(r.counts.checked)}
                  {r.status === "running" && r.planned ? <span className="text-zinc-400"> of {r.planned}</span> : null}
                </td>
                <td className="px-3 py-2 text-zinc-900 dark:text-zinc-100">
                  {n(r.counts.kept)}
                  {r.counts.checked ? <span className="ml-1 text-[11px] text-zinc-400">{pct(r.counts.kept ?? 0, r.counts.checked)}</span> : null}
                </td>
                <td className="px-3 py-2">{n(r.counts.no_india_jobs)}</td>
                <td className="px-3 py-2">{n(r.counts.no_board)}</td>
                <td className="px-3 py-2">
                  {n(r.india_jobs)}
                  {r.matching_jobs ? <span className="ml-1 text-[11px] text-zinc-400">{r.matching_jobs} matching</span> : null}
                </td>
                <td className="px-3 py-2 pr-5">
                  <StatusBadge r={r} />
                </td>
              </tr>
              {isOpen && (
                <tr>
                  <td colSpan={10} className="bg-zinc-50/60 p-0 dark:bg-zinc-900/40">
                    <RunDetail r={r} />
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

function Breakdown({ title, rows, read, hint }: { title: string; rows: FinderBreakdownRow[]; read?: Record<string, number>; hint: string }) {
  return (
    <Card className="overflow-x-auto">
      <div className="px-5 pt-5">
        <SectionHead title={title} />
        <p className="-mt-1 mb-3 text-xs text-zinc-500">{hint}</p>
      </div>
      <table className="w-full min-w-[40rem] text-left text-sm">
        <thead>
          <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
            {["", "Companies", "Waiting", "Checked", "Kept", "Kept rate", "No India jobs", "No board", "India jobs", ...(read ? ["Scans read"] : [])].map((h, i) => (
              <th key={i} className="px-3 py-2 font-medium first:pl-5">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 tabular-nums dark:divide-zinc-800">
          {rows.map((r) => {
            const checked = r.total - r.pending;
            return (
              <tr key={r.key}>
                <td className="py-2 pr-3 pl-5 text-zinc-900 dark:text-zinc-100">{r.label}</td>
                <td className="px-3 py-2">{n(r.total)}</td>
                <td className="px-3 py-2 text-zinc-500">{n(r.pending)}</td>
                <td className="px-3 py-2">{n(checked)}</td>
                <td className="px-3 py-2 text-zinc-900 dark:text-zinc-100">{n(r.kept)}</td>
                <td className="px-3 py-2">{pct(r.kept, checked)}</td>
                <td className="px-3 py-2">{n(r.no_india_jobs)}</td>
                <td className="px-3 py-2">{n(r.no_board)}</td>
                <td className="px-3 py-2">{n(r.india_jobs)}</td>
                {read && <td className="px-3 py-2 pr-5">{n(read[r.key])}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}

export default function CompanyFinderAnalytics() {
  const toast = useToast();
  const [starting, setStarting] = useState(false);
  const { data, error, reload } = useResource(() => api.finderDashboard(), {
    pollMs: 8000,
    // While a run is going, or the next one is about to start by itself.
    shouldPoll: (d: FinderDashboardOut) => d.status.running || (d.status.auto && d.status.due_now > 0),
  });
  const st = data?.status;
  const runNow = async () => {
    setStarting(true);
    try {
      await api.runFinder();
      toast.info("Run started", "It runs in the background; this page updates as it goes.");
      void reload();
    } catch (e) {
      toast.error("Couldn't start a run", errorMessage(e));
    } finally {
      setStarting(false);
    }
  };

  const kept = st?.by_status.kept ?? 0;
  const pending = st?.by_status.pending ?? 0;
  const total = Object.values(st?.by_status ?? {}).reduce((a, b) => a + b, 0);
  const checked = total - pending;
  const indiaJobs = (data?.by_kind ?? []).reduce((a, r) => a + r.india_jobs, 0);
  const current = data?.runs.find((r) => r.status === "running");

  return (
    <div>
      <PageHeader
        title="Company finder"
        subtitle="Finds companies whose job boards have jobs in India, or remote jobs open to India, and adds them to the companies every scan reads. It runs by itself while the app runs, one run after another while companies are waiting. Free: public lists and boards only."
        actions={
          st?.enabled ? (
            <Button size="sm" icon={<Play className="size-3.5" />} loading={starting} disabled={st.running} onClick={() => void runNow()}>
              {st.running ? "Running…" : "Run now"}
            </Button>
          ) : null
        }
      />
      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} onRetry={reload} />
        </div>
      )}
      {st && !st.server_allows && (
        <p className="mb-6 text-sm text-zinc-600 dark:text-zinc-400">
          The finder doesn't run on this server (COMPANY_FINDER=false). It runs on your local app; this page shows the runs that came with
          the database.
        </p>
      )}
      {!data && !error && (
        <div className="space-y-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-56" />
        </div>
      )}
      {data && st && (
        <div className="space-y-8">
          <Card className="px-5 py-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-800 dark:text-zinc-200">
              {st.running && <Spinner className="size-3.5" />}
              <span>
                {!st.enabled
                  ? "Switched off ([scout.search.finder] enabled = false)."
                  : st.running
                    ? `Run ${st.run_id ?? ""}: ${st.message ?? "working"}`
                    : st.finished_at
                      ? `Last run ${timeAgo(st.finished_at)}: ${st.message ?? ""}`
                      : "Not run yet"}
              </span>
              {st.error && <span className="text-xs text-rose-600 dark:text-rose-400">{st.error}</span>}
            </div>
            {current && current.planned > 0 && (
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800" role="progressbar" aria-valuenow={current.counts.checked ?? 0} aria-valuemax={current.planned}>
                <div className="h-full rounded-full bg-violet-600 dark:bg-violet-400" style={{ width: `${Math.min(100, ((current.counts.checked ?? 0) / current.planned) * 100)}%` }} />
              </div>
            )}
            <p className="mt-2 text-xs text-zinc-500">
              {st.auto
                ? st.due_now > 0
                  ? `Automatic: ${st.due_now.toLocaleString()} companies due, so the next run starts about 30 s after this one ends.`
                  : "Automatic: nothing due; it looks again every few hours for a new web-index crawl, new YC companies and companies due for a re-check."
                : "Automatic runs are off (Admin settings → Company finder)."}{" "}
              Each run checks up to {st.board_checks_per_run} companies whose board is known and {st.leads_per_run} whose board has to be searched for. Settings:{" "}
              <Link to="/admin#finder" className="text-violet-700 hover:underline dark:text-violet-300">
                Admin settings
              </Link>
              .
            </p>
            {st.crawl && (st.crawl.collection || st.crawl.collections_done.length > 0) && (
              <p className="mt-1 text-xs text-zinc-500">
                Web index: {st.crawl.collections_done.length ? `read ${st.crawl.collections_done.join(", ")}` : "not finished yet"}
                {st.crawl.collection ? ` · reading ${st.crawl.collection}` : ""} · {st.crawl.leads.toLocaleString()} board addresses found
              </p>
            )}
          </Card>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Tile label="Companies scans read" value={data.companies_read.toLocaleString()} hint="starter, found from jobs, and kept here" />
            <Tile label="Kept by the finder" value={kept.toLocaleString()} hint={`${pct(kept, checked)} of those checked`} />
            <Tile label="Checked" value={checked.toLocaleString()} hint={`of ${total.toLocaleString()} found`} />
            <Tile label="Waiting" value={pending.toLocaleString()} hint={`${st.due_now.toLocaleString()} due now (incl. re-checks)`} />
            <Tile label="India jobs on kept boards" value={indiaJobs.toLocaleString()} hint="when each was checked" />
            <Tile label="Runs" value={data.runs.length.toLocaleString()} hint={data.runs.length ? `last ${timeAgo(data.runs[0].started_at)}` : undefined} />
          </div>

          <Card className="p-5">
            <SectionHead title="What each run's checks found" extra={<Legend />} />
            <RunsChart runs={data.runs} />
          </Card>

          <Card className="overflow-x-auto">
            <div className="px-5 pt-5">
              <SectionHead title="Runs" />
              <p className="-mt-1 mb-3 text-xs text-zinc-500">Click a run for its companies kept, its hiring systems, and what it added to the waiting list.</p>
            </div>
            <RunsTable runs={data.runs} />
          </Card>

          <Breakdown
            title="By hiring system"
            rows={data.by_kind}
            read={data.companies_read_by_kind}
            hint="Every company checked so far (and web-index companies waiting), grouped by the system its job board runs on. “Scans read” counts all companies scans read on that system."
          />
          <Breakdown title="By where they came from" rows={data.by_origin} hint="Seed list = Indian companies we listed; YC list = Y Combinator companies in India; Web index = board addresses from Common Crawl." />
        </div>
      )}
    </div>
  );
}
