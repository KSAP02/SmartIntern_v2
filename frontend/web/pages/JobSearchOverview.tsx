import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, BarChart3, Brain, Radar } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import type { DayCount, OverviewOut, ScanOut, ScheduleSettings } from "../lib/types";
import { cx, timeAgo, useResource } from "../lib/util";
import { Badge, Button, Card, EmptyState, ErrorBanner, PageHeader, Segmented, Skeleton, Spinner, Toggle } from "../components/ui";
import { useToast } from "../components/Toast";
import { PHASE_LABEL, clockTime, dateTime, plural, valueLabel } from "../components/jobs/format";
import { QuotaMeter } from "../components/jobs/SearchPlan";
import { ScanPicker } from "../components/jobs/ScanPicker";
import { RequestResults } from "../components/jobs/RequestResults";
import { JobDetailPanel } from "../components/jobs/JobDetailPanel";

const FUNNEL: { key: string; label: string }[] = [
  { key: "seen", label: "Seen" },
  { key: "excluded", label: "Excluded by criteria" },
  { key: "not_relevant", label: "Not relevant" },
  { key: "relevant", label: "Relevant" },
  { key: "mapped", label: "Mapped" },
  { key: "fits_preset", label: "Fits your preset" },
];

const TOTALS: { key: string; label: string }[] = [
  { key: "fetched", label: "fetched" },
  { key: "new", label: "new" },
  { key: "updated", label: "updated" },
  { key: "duplicates", label: "duplicates" },
  { key: "excluded", label: "excluded" },
  { key: "not_relevant", label: "not relevant" },
  { key: "relevant", label: "relevant" },
  { key: "mapped", label: "mapped" },
];

// Neutral / clay tones for stacked series, in order.
const SERIES = [
  "fill-violet-600 bg-violet-600 dark:fill-violet-400 dark:bg-violet-400",
  "fill-zinc-500 bg-zinc-500 dark:fill-zinc-400 dark:bg-zinc-400",
  "fill-violet-300 bg-violet-300 dark:fill-violet-700 dark:bg-violet-700",
  "fill-zinc-300 bg-zinc-300 dark:fill-zinc-600 dark:bg-zinc-600",
  "fill-violet-800 bg-violet-800 dark:fill-violet-200 dark:bg-violet-200",
  "fill-zinc-700 bg-zinc-700 dark:fill-zinc-200 dark:bg-zinc-200",
];

function SectionHead({ title, extra }: { title: string; extra?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-xs font-semibold tracking-wider text-zinc-400 uppercase">{title}</h2>
      {extra}
    </div>
  );
}

function StatusDotSmall({ status }: { status: "running" | "ok" | "failed" }) {
  return (
    <span
      title={status}
      className={cx(
        "inline-block size-2 shrink-0 rounded-full",
        status === "ok" && "bg-emerald-500",
        status === "failed" && "bg-rose-500",
        status === "running" && "animate-pulse bg-violet-500",
      )}
    />
  );
}

function ScanProgress({ scan, labels }: { scan: ScanOut; labels: Map<string, string> }) {
  const phases = ["fetching", "processing", "mapping", "pruning"] as const;
  const at = phases.indexOf(scan.phase as (typeof phases)[number]);
  return (
    <Card className="mb-8 p-5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Spinner className="text-violet-600 dark:text-violet-400" />
        <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Scanning · started {timeAgo(scan.started_at)}</p>
        <ol className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="Scan phases">
          {phases.map((p, i) => (
            <li key={p} className="flex items-center gap-1.5">
              {i > 0 && <span className="h-px w-3 bg-zinc-300 dark:bg-zinc-700" />}
              <span
                aria-current={i === at ? "step" : undefined}
                className={cx(i === at ? "font-medium text-violet-700 dark:text-violet-300" : i < at ? "text-zinc-600 dark:text-zinc-300" : "text-zinc-400")}
              >
                {PHASE_LABEL[p]}
              </span>
            </li>
          ))}
        </ol>
      </div>
      {scan.runs.length > 0 && (
        <ul className="mt-4 divide-y divide-zinc-100 border-t border-zinc-100 dark:divide-zinc-800 dark:border-zinc-800">
          {scan.runs.map((r, i) => (
            <li key={`${r.source}-${r.company ?? ""}-${i}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-xs">
              <StatusDotSmall status={r.status} />
              <span className="font-medium text-zinc-800 dark:text-zinc-200">
                {labels.get(r.source) ?? r.source}
                {r.company && <span className="font-normal text-zinc-500"> · {r.company}</span>}
              </span>
              <span className="text-zinc-500 tabular-nums">
                {r.fetched} fetched · {r.new} new
              </span>
              {r.error && <span className="w-full truncate text-rose-600/80 dark:text-rose-400/80" title={r.error}>{r.error}</span>}
            </li>
          ))}
        </ul>
      )}
      <Totals totals={scan.totals} className="mt-3" />
    </Card>
  );
}

function Totals({ totals, className }: { totals: Record<string, number>; className?: string }) {
  const shown = TOTALS.filter((t) => totals[t.key] !== undefined);
  if (!shown.length) return null;
  return (
    <p className={cx("text-xs text-zinc-500 tabular-nums dark:text-zinc-400", className)}>
      {shown.map((t, i) => (
        <span key={t.key}>
          {i > 0 && " · "}
          <span className="text-zinc-700 dark:text-zinc-300">{totals[t.key].toLocaleString()}</span> {t.label}
        </span>
      ))}
    </p>
  );
}

function Funnel({ funnel }: { funnel: Record<string, number> }) {
  // gap-px over a hairline-coloured background draws thin dividers at any column count
  return (
    <div className="mb-8 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-zinc-200 bg-zinc-200 sm:grid-cols-3 lg:grid-cols-6 dark:border-zinc-800 dark:bg-zinc-800">
      {FUNNEL.map((f) => (
        <div key={f.key} className="bg-zinc-50 px-4 py-4 dark:bg-zinc-950">
          <p className={cx("font-serif text-2xl tabular-nums", f.key === "fits_preset" ? "text-violet-700 dark:text-violet-300" : "text-zinc-900 dark:text-zinc-50")}>
            {(funnel[f.key] ?? 0).toLocaleString()}
          </p>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{f.label}</p>
        </div>
      ))}
    </div>
  );
}

function lastDays(n: number): string[] {
  const out: string[] = [];
  const now = new Date();
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);
  }
  return out;
}

function shortDate(ymd: string): string {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Small stacked bar chart: one bar per day, stacked by source. No chart library. */
function PerDayChart({ data, labels }: { data: DayCount[]; labels: Map<string, string> }) {
  const [metric, setMetric] = useState<"found" | "new">("found");
  const days = useMemo(() => {
    const fromData = data.map((d) => d.date).sort();
    const base = lastDays(30);
    // Use the server's dates if they fall outside our local window (timezone differences).
    return fromData.length && fromData[fromData.length - 1] > base[base.length - 1] ? [...base.slice(1), fromData[fromData.length - 1]] : base;
  }, [data]);
  const sources = useMemo(() => {
    const totals = new Map<string, number>();
    for (const d of data) totals.set(d.source, (totals.get(d.source) ?? 0) + d.found);
    return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([s]) => s);
  }, [data]);
  const byDay = useMemo(() => {
    const m = new Map<string, Map<string, DayCount>>();
    for (const d of data) {
      if (!m.has(d.date)) m.set(d.date, new Map());
      m.get(d.date)!.set(d.source, d);
    }
    return m;
  }, [data]);

  const totalOf = (day: string) => sources.reduce((s, src) => s + (byDay.get(day)?.get(src)?.[metric] ?? 0), 0);
  const max = Math.max(1, ...days.map(totalOf));
  const sum = days.reduce((s, d) => s + totalOf(d), 0);

  const W = 10;
  const H = 100;
  const gap = 2;

  return (
    <Card className="mb-8 p-5">
      <SectionHead
        title="Jobs found per day"
        extra={
          <Segmented
            value={metric}
            onChange={setMetric}
            options={[
              { value: "found", label: "Found" },
              { value: "new", label: "New" },
            ]}
          />
        }
      />
      {data.length === 0 || sum === 0 ? (
        <EmptyState icon={<BarChart3 className="size-5" />} title="Nothing yet" body="Once a scan runs, jobs found each day show up here, split by source." />
      ) : (
        <>
          <div className="flex gap-2">
            <div className="flex h-40 flex-col justify-between text-right text-[10px] text-zinc-400 tabular-nums">
              <span>{max}</span>
              <span>0</span>
            </div>
            <div className="min-w-0 flex-1">
              <svg
                viewBox={`0 0 ${days.length * W} ${H}`}
                preserveAspectRatio="none"
                className="h-40 w-full border-b border-zinc-200 dark:border-zinc-800"
                role="img"
                aria-label={`${metric === "found" ? "Jobs found" : "New jobs"} per day for the last ${days.length} days, ${sum} in total`}
              >
                {days.map((day, i) => {
                  let y = H;
                  const total = totalOf(day);
                  return (
                    <g key={day}>
                      <title>
                        {`${shortDate(day)}: ${total} ${metric}` +
                          sources
                            .map((s) => {
                              const v = byDay.get(day)?.get(s)?.[metric] ?? 0;
                              return v ? `\n${labels.get(s) ?? s}: ${v}` : "";
                            })
                            .join("")}
                      </title>
                      {/* full-height hit area so the tooltip works on empty days too */}
                      <rect x={i * W} y={0} width={W} height={H} className="fill-transparent" />
                      {sources.map((s, si) => {
                        const v = byDay.get(day)?.get(s)?.[metric] ?? 0;
                        if (!v) return null;
                        const h = (v / max) * H;
                        y -= h;
                        return <rect key={s} x={i * W + gap / 2} y={y} width={W - gap} height={h} className={SERIES[si % SERIES.length]} />;
                      })}
                    </g>
                  );
                })}
              </svg>
              <div className="mt-1 flex justify-between text-[10px] text-zinc-400">
                <span>{shortDate(days[0])}</span>
                <span>{shortDate(days[Math.floor(days.length / 2)])}</span>
                <span>{shortDate(days[days.length - 1])}</span>
              </div>
            </div>
          </div>
          <ul className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-zinc-600 dark:text-zinc-400">
            {sources.map((s, si) => (
              <li key={s} className="flex items-center gap-1.5">
                <span className={cx("inline-block size-2.5 rounded-sm", SERIES[si % SERIES.length])} />
                {labels.get(s) ?? s}
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

function Breakdown({ breakdown }: { breakdown: Record<string, Record<string, number>> }) {
  const groups = [
    { key: "category", title: "Job type" },
    { key: "workplace", title: "Workplace" },
    { key: "country", title: "Country" },
  ];
  return (
    <div className="mb-8">
      <SectionHead title="Relevant jobs by" />
      <div className="grid gap-4 md:grid-cols-3">
        {groups.map((g) => {
          const entries = Object.entries(breakdown[g.key] ?? {}).sort((a, b) => b[1] - a[1]);
          const top = Math.max(1, ...entries.map(([, v]) => v));
          return (
            <Card key={g.key} className="p-4">
              <p className="mb-3 text-sm font-medium text-zinc-900 dark:text-zinc-100">{g.title}</p>
              {entries.length === 0 ? (
                <p className="text-xs text-zinc-500">No data yet.</p>
              ) : (
                <ul className="space-y-2">
                  {entries.slice(0, 8).map(([k, v]) => (
                    <li key={k}>
                      <div className="flex items-center justify-between gap-2 text-xs">
                        <span className="truncate text-zinc-700 dark:text-zinc-300">{valueLabel(g.key, k)}</span>
                        <span className="text-zinc-500 tabular-nums">{v.toLocaleString()}</span>
                      </div>
                      <div className="mt-1 h-1 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
                        <div className="h-full rounded-full bg-violet-600/80 dark:bg-violet-400/80" style={{ width: `${(v / top) * 100}%` }} />
                      </div>
                    </li>
                  ))}
                  {entries.length > 8 && <li className="text-[11px] text-zinc-400">+{entries.length - 8} more</li>}
                </ul>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function SourcesHealth({ data }: { data: OverviewOut }) {
  return (
    <div className="mb-8">
      <SectionHead
        title="Source"
        extra={
          <Link to="/job-search/settings#plan" className="inline-flex items-center gap-1 text-xs font-medium text-violet-700 hover:underline dark:text-violet-300">
            Search plan <ArrowRight className="size-3" />
          </Link>
        }
      />
      {data.quota && (
        <Card className="mb-3 px-4 py-3">
          <QuotaMeter q={data.quota} />
        </Card>
      )}
      <Card className="overflow-x-auto">
        {data.sources.length === 0 ? (
          <p className="px-4 py-5 text-sm text-zinc-500">No sources configured.</p>
        ) : (
          <table className="w-full min-w-[34rem] text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
                <th className="px-4 py-2 font-medium">Source</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Last success</th>
                <th className="px-4 py-2 text-right font-medium">Active jobs</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {data.sources.map((s) => {
                const failing = !!s.last_error && (!s.last_success_at || (s.last_error_at ?? "") > s.last_success_at);
                return (
                  <tr key={s.name} className={cx(!s.enabled && "opacity-55")}>
                    <td className="px-4 py-2.5">
                      <span className="text-zinc-900 dark:text-zinc-100">{s.label}</span>
                      {s.kind === "ats" && <span className="ml-1.5 text-[11px] text-zinc-400">ATS</span>}
                      {failing && (
                        <p className="mt-0.5 max-w-xs truncate text-xs text-rose-600/80 dark:text-rose-400/80" title={s.last_error ?? undefined}>
                          {s.last_error}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-2.5">{s.enabled ? <Badge tone={failing ? "red" : "neutral"}>{failing ? "Failing" : "On"}</Badge> : <Badge>Off</Badge>}</td>
                    <td className="px-4 py-2.5 text-xs text-zinc-500">{s.last_success_at ? timeAgo(s.last_success_at) : "Never"}</td>
                    <td className="px-4 py-2.5 text-right text-zinc-700 tabular-nums dark:text-zinc-300">{s.active_jobs.toLocaleString()}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function RecentScans({ scans, error, onRetry }: { scans: ScanOut[] | null; error: string | null; onRetry: () => void }) {
  return (
    <div>
      <SectionHead title="Recent scans" />
      {error && <ErrorBanner message={error} onRetry={onRetry} />}
      {!scans && !error && <Skeleton className="h-24" />}
      {scans && scans.length === 0 && <p className="text-sm text-zinc-500">No scans yet.</p>}
      {scans && scans.length > 0 && (
        <Card>
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {scans.slice(0, 10).map((s) => (
              <li key={s.scan_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3">
                <span className="text-sm text-zinc-900 tabular-nums dark:text-zinc-100">{dateTime(s.started_at)}</span>
                <Badge tone={s.trigger === "auto" ? "neutral" : "accent"}>{s.trigger}</Badge>
                {s.phase === "done" ? (
                  <span className="text-xs text-zinc-500">Done</span>
                ) : s.phase === "failed" ? (
                  <span className="text-xs text-rose-600/80 dark:text-rose-400/80" title={s.error ?? undefined}>
                    Failed{s.error ? `: ${s.error}` : ""}
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 text-xs text-zinc-500">
                    <Spinner className="size-3" /> {PHASE_LABEL[s.phase]}
                  </span>
                )}
                <Totals totals={s.totals} className="w-full" />
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

export default function JobSearchOverview() {
  const toast = useToast();
  const overview = useResource(api.searchOverview, { pollMs: 2000, shouldPoll: (o) => !!o.running });
  const scans = useResource(api.listScans);
  const [schedule, setSchedule] = useState<ScheduleSettings | null>(null);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    api
      .getSearchSettings()
      .then((s) => setSchedule(s.schedule))
      .catch(() => {});
  }, []);

  // When a running scan finishes, refresh the scan history and say so.
  const wasRunning = useRef(false);
  const data = overview.data;
  useEffect(() => {
    if (!data) return;
    const running = !!data.running;
    if (wasRunning.current && !running) {
      void scans.reload();
      void calls.reload();
      const last = data.last_scan;
      if (last?.phase === "failed") toast.error("Scan failed", last.error ?? undefined);
      else if (last) toast.success("Scan finished", `${last.totals.new ?? 0} new · ${last.totals.relevant ?? 0} relevant`);
    }
    if (!wasRunning.current && running) void scans.reload();
    wasRunning.current = running;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const labels = useMemo(() => new Map((data?.sources ?? []).map((s) => [s.name, s.label])), [data]);

  const [picking, setPicking] = useState(false);
  const [openJob, setOpenJob] = useState<number | null>(null);
  const calls = useResource(() => api.listApiCalls(20));
  const started = (s: ScanOut) => {
    overview.setData((o) => (o ? { ...o, running: s } : o));
    void overview.reload();
    toast.info("Scan started");
  };

  const setAuto = async (enabled: boolean) => {
    setToggling(true);
    try {
      const s = await api.setAutoscan(enabled);
      setSchedule(s);
      void overview.reload();
      toast.success(enabled ? "Auto-scan on" : "Auto-scan off");
    } catch (e) {
      toast.error("Couldn't change auto-scan", errorMessage(e));
    } finally {
      setToggling(false);
    }
  };

  const autoscan = schedule?.autoscan ?? data?.autoscan ?? false;
  const cadence = schedule ? `${schedule.every_hours === 12 ? "Every 12 h from" : "Daily at"} ${schedule.time} (${schedule.timezone})` : null;

  const subtitle = data
    ? [
        data.last_scan ? `Last scan ${timeAgo(data.last_scan.finished_at ?? data.last_scan.started_at)}` : "No scans yet",
        data.autoscan && data.next_scan_at ? `next ${clockTime(data.next_scan_at)}` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : "Finds jobs from your sources and checks them against your memory.";

  return (
    <div>
      <PageHeader
        title="Scan Jobs"
        subtitle={subtitle}
        actions={
          <>
            <label className="flex items-center gap-2.5 pr-2 text-sm text-zinc-700 dark:text-zinc-300">
              <Toggle checked={autoscan} disabled={toggling || (!schedule && !data)} onChange={(v) => void setAuto(v)} label="Auto-scan" />
              <span className="leading-tight">
                Auto-scan
                {cadence && <span className="block text-[11px] text-zinc-400">{cadence}</span>}
              </span>
            </label>
            <Button variant="primary" icon={<Radar className="size-4" />} loading={!!data?.running} disabled={!!data?.running} onClick={() => setPicking(true)}>
              {data?.running ? "Scanning…" : "Scan now"}
            </Button>
          </>
        }
      />

      {overview.error && (
        <div className="mb-6">
          <ErrorBanner message={overview.error} onRetry={overview.reload} />
        </div>
      )}

      {overview.loading && !data && (
        <div className="space-y-4">
          <Skeleton className="h-20" />
          <Skeleton className="h-52" />
          <Skeleton className="h-40" />
        </div>
      )}

      {data && (
        <>
          {!data.memory_ready && (
            <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-zinc-200 px-4 py-3 text-sm text-zinc-700 dark:border-zinc-800 dark:text-zinc-300">
              <span className="flex items-center gap-2">
                <Brain className="size-4 text-violet-600 dark:text-violet-400" />
                A role has no role context yet: its jobs are judged by title only until it's written.
              </span>
              <Link to="/memory/roles">
                <Button size="sm">Role contexts</Button>
              </Link>
            </div>
          )}

          {data.running && <ScanProgress scan={data.running} labels={labels} />}

          <Funnel funnel={data.funnel} />
          <PerDayChart data={data.per_day} labels={labels} />
          <Breakdown breakdown={data.breakdown} />
          <SourcesHealth data={data} />
          <RequestResults calls={calls.data} error={calls.error} onRetry={calls.reload} onOpenJob={setOpenJob} />
          <RecentScans scans={scans.data} error={scans.error} onRetry={scans.reload} />

          {(data.funnel.relevant ?? 0) > 0 && (
            <p className="mt-8 text-sm text-zinc-500">
              {plural(data.funnel.relevant ?? 0, "relevant job")} waiting.{" "}
              <Link to="/job-search/jobs" className="font-medium text-violet-700 hover:underline dark:text-violet-300">
                Open Jobs
              </Link>
            </p>
          )}
        </>
      )}
      <ScanPicker open={picking} onClose={() => setPicking(false)} onStarted={started} />
      <JobDetailPanel jobId={openJob} onClose={() => setOpenJob(null)} onChanged={() => void calls.reload()} />
    </div>
  );
}
