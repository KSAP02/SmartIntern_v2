import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { BarChart3, ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import type { JSearchAnalyticsOut, ProviderUsageOut, UsageDay } from "../lib/types";
import { cx, timeAgo, useResource } from "../lib/util";
import { Button, Card, EmptyState, ErrorBanner, PageHeader, Segmented, Skeleton } from "../components/ui";
import { useToast } from "../components/Toast";
import { QuotaMeter } from "../components/jobs/SearchPlan";
import { dateTime } from "../components/jobs/format";

type Metric = "requests" | "new_jobs" | "relevant_jobs";
const METRIC_LABEL: Record<Metric, string> = { requests: "Requests", new_jobs: "New jobs", relevant_jobs: "Relevant jobs" };

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

const shortDate = (d: string) => new Date(`${d}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });

/** OpenWeb Ninja's own view of the plan (fetched on demand, not on every page load). */
function ProviderUsage({ u, provider, configured, onRefresh, refreshing }: { u: ProviderUsageOut; provider: string; configured: boolean; onRefresh: () => void; refreshing: boolean }) {
  const [open, setOpen] = useState(false);
  const known = u.limit != null || u.used != null || u.remaining != null || u.plan;
  return (
    <Card className="p-5">
      <SectionHead
        title="Your plan (from OpenWeb Ninja)"
        extra={
          <Button size="sm" icon={<RefreshCw className="size-3.5" />} loading={refreshing} disabled={!configured || provider !== "openwebninja"} onClick={onRefresh}>
            Check usage
          </Button>
        }
      />
      {provider !== "openwebninja" ? (
        <p className="text-sm text-zinc-500">Usage can only be read with an OpenWeb Ninja key. Switch the provider in Admin settings → JSearch.</p>
      ) : !u.fetched_at && !u.error ? (
        <p className="text-sm text-zinc-500">Not checked yet. “Check usage” asks OpenWeb Ninja for your plan, billing period and requests left (it is not a job search). Scans also refresh it every 6 hours.</p>
      ) : (
        <>
          {u.error && <p className="mb-3 text-sm text-rose-600/80 dark:text-rose-400/80">{u.error}</p>}
          {known ? (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
              {[
                ["Plan", u.plan ?? "—"],
                ["Used", u.used ?? "—"],
                ["Left", u.remaining ?? "—"],
                ["Limit", u.limit ?? "—"],
              ].map(([k, v]) => (
                <div key={String(k)}>
                  <dt className="text-[11px] text-zinc-500">{k}</dt>
                  <dd className="mt-0.5 text-lg text-zinc-900 tabular-nums dark:text-zinc-100">{v}</dd>
                </div>
              ))}
            </dl>
          ) : (
            u.fetched_at && <p className="text-sm text-zinc-500">The answer didn't use field names we recognise; see the details below.</p>
          )}
          <p className="mt-3 text-xs text-zinc-500">
            {(u.period_start || u.period_end) && `Billing period ${u.period_start ?? "?"} → ${u.period_end ?? "?"} · `}
            {u.fetched_at ? `checked ${timeAgo(u.fetched_at)}` : ""}
          </p>
          {u.raw.length > 0 && (
            <div className="mt-3 border-t border-zinc-100 pt-3 dark:border-zinc-800">
              <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="flex items-center gap-1 text-xs font-medium text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">
                {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                Everything OpenWeb Ninja returned
              </button>
              {open && (
                <dl className="mt-2 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
                  {u.raw.map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="truncate font-mono text-zinc-500">{k}</dt>
                      <dd className="truncate text-zinc-800 dark:text-zinc-200">{String(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

/** One series per view (the metric switch), so no legend: the title names it. */
function DailyChart({ days, metric }: { days: UsageDay[]; metric: Metric }) {
  const max = Math.max(1, ...days.map((d) => d[metric]));
  const sum = days.reduce((s, d) => s + d[metric], 0);
  const W = 10;
  const H = 100;
  const gap = 2;
  if (sum === 0) return <EmptyState icon={<BarChart3 className="size-5" />} title="Nothing in this period" body="Requests appear here once a scan (or calibration) calls JSearch." />;
  return (
    <div className="flex gap-2">
      <div className="flex h-40 flex-col justify-between text-right text-[10px] text-zinc-400 tabular-nums">
        <span>{max}</span>
        <span>0</span>
      </div>
      <div className="min-w-0 flex-1">
        <svg viewBox={`0 0 ${days.length * W} ${H}`} preserveAspectRatio="none" className="h-40 w-full border-b border-zinc-200 dark:border-zinc-800" role="img" aria-label={`${METRIC_LABEL[metric]} per day, ${sum} in total`}>
          {days.map((d, i) => {
            const v = d[metric];
            const h = (v / max) * H;
            return (
              <g key={d.date}>
                <title>{`${shortDate(d.date)}: ${d.requests} requests · ${d.results} jobs · ${d.new_jobs} new · ${d.relevant_jobs} relevant${d.errors ? ` · ${d.errors} failed` : ""}`}</title>
                <rect x={i * W} y={0} width={W} height={H} className="fill-transparent" />
                {v > 0 && <rect x={i * W + gap / 2} y={H - h} width={W - gap} height={h} rx={1.5} className="fill-violet-600 dark:fill-violet-400" />}
              </g>
            );
          })}
        </svg>
        <div className="mt-1 flex justify-between text-[10px] text-zinc-400">
          <span>{shortDate(days[0].date)}</span>
          <span>{shortDate(days[Math.floor(days.length / 2)].date)}</span>
          <span>{shortDate(days[days.length - 1].date)}</span>
        </div>
      </div>
    </div>
  );
}

function DailyTable({ days }: { days: UsageDay[] }) {
  const rows = days.filter((d) => d.requests > 0).reverse();
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[30rem] text-left text-xs">
        <thead>
          <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
            {["Day", "Requests", "Jobs returned", "New", "Relevant", "Failed"].map((h) => (
              <th key={h} className="px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 tabular-nums dark:divide-zinc-800">
          {rows.map((d) => (
            <tr key={d.date}>
              <td className="px-3 py-2 text-zinc-500">{shortDate(d.date)}</td>
              <td className="px-3 py-2 text-zinc-900 dark:text-zinc-100">{d.requests}</td>
              <td className="px-3 py-2">{d.results}</td>
              <td className="px-3 py-2">{d.new_jobs}</td>
              <td className="px-3 py-2">{d.relevant_jobs}</td>
              <td className="px-3 py-2">{d.errors || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function JSearchAnalytics() {
  const toast = useToast();
  const [days, setDays] = useState(30);
  const [metric, setMetric] = useState<Metric>("requests");
  const [showTable, setShowTable] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const { data, setData, error, loading, reload } = useResource(() => api.getJSearchAnalytics(days), {});
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days]);

  const refreshUsage = async () => {
    setRefreshing(true);
    try {
      const usage = await api.refreshJSearchUsage();
      setData((d: JSearchAnalyticsOut | null) => (d ? { ...d, usage } : d));
      if (usage.error) toast.error("Couldn't read usage", usage.error);
      void reload();
    } catch (e) {
      toast.error("Couldn't read usage", errorMessage(e));
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="JSearch analytics"
        subtitle="How many requests you have, how many the app has used, and what they found. One request = one page of up to 10 jobs."
        actions={
          <Segmented
            value={String(days)}
            onChange={(x) => setDays(Number(x))}
            options={[
              { value: "7", label: "7 days" },
              { value: "30", label: "30 days" },
              { value: "90", label: "90 days" },
            ]}
          />
        }
      />

      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} onRetry={reload} />
        </div>
      )}
      {!data && !error && (
        <div className="space-y-4">
          <Skeleton className="h-28" />
          <Skeleton className="h-56" />
        </div>
      )}

      {data && (
        <div className="space-y-8">
          {!data.configured && (
            <p className="rounded-md border border-amber-300/60 bg-amber-50/60 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
              JSEARCH_API_KEY isn't set yet: add it to the root .env, then run docker compose up -d.
            </p>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <ProviderUsage u={data.usage} provider={data.provider} configured={data.configured} onRefresh={() => void refreshUsage()} refreshing={refreshing} />
            <Card className="p-5">
              <SectionHead
                title="The app's budget"
                extra={
                  <Link to="/admin#sources" className="text-xs font-medium text-violet-700 hover:underline dark:text-violet-300">
                    Budget rules
                  </Link>
                }
              />
              <QuotaMeter q={data.quota} />
              {data.quota.provider_remaining != null && (
                <p className="mt-2 text-xs text-zinc-500">
                  OpenWeb Ninja says {data.quota.provider_remaining} left; the app never plans past that.
                </p>
              )}
            </Card>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Tile label="Requests" value={data.totals.requests} hint={`${data.totals.scan} scan · ${data.totals.calibration} test`} />
            <Tile label="Jobs returned" value={data.totals.results} hint={data.per_request.results != null ? `${data.per_request.results} per request` : undefined} />
            <Tile label="New jobs" value={data.totals.new_jobs} hint={data.per_request.new_jobs != null ? `${data.per_request.new_jobs} per request` : undefined} />
            <Tile label="Relevant" value={data.totals.relevant_jobs} hint={data.per_request.relevant_jobs != null ? `${data.per_request.relevant_jobs} per request` : undefined} />
            <Tile label="New rate" value={data.totals.results ? `${Math.round((data.totals.new_jobs / data.totals.results) * 100)}%` : "—"} hint="of jobs returned were new" />
            <Tile label="Failed" value={data.totals.errors} hint="still counted by the provider" />
          </div>

          <Card className="p-5">
            <SectionHead
              title={`${METRIC_LABEL[metric]} per day`}
              extra={
                <div className="flex flex-wrap items-center gap-2">
                  <Segmented value={metric} onChange={setMetric} options={(Object.keys(METRIC_LABEL) as Metric[]).map((m) => ({ value: m, label: METRIC_LABEL[m] }))} />
                  <Button size="sm" variant="ghost" onClick={() => setShowTable((t) => !t)}>
                    {showTable ? "Chart" : "Table"}
                  </Button>
                </div>
              }
            />
            {showTable ? <DailyTable days={data.per_day} /> : <DailyChart days={data.per_day} metric={metric} />}
          </Card>

          <Card className="overflow-x-auto">
            <div className="px-5 pt-5">
              <SectionHead title="Searches (all time)" />
            </div>
            {data.queries.length === 0 ? (
              <p className="px-5 pb-5 text-sm text-zinc-500">No searches yet: set Roles you want in Search Settings.</p>
            ) : (
              <table className="w-full min-w-[38rem] text-left text-sm">
                <thead>
                  <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
                    {["Search", "Requests", "Returned", "New", "Relevant", "Relevant / request", "Runs"].map((h) => (
                      <th key={h} className="px-5 py-2 font-medium first:pl-5">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 tabular-nums dark:divide-zinc-800">
                  {data.queries.map((q) => (
                    <tr key={q.id} className={cx((!q.active || !q.enabled) && "opacity-55")}>
                      <td className="px-5 py-2.5 text-zinc-900 dark:text-zinc-100">
                        {q.query}
                        {!q.active && <span className="ml-2 text-[11px] text-zinc-400">not in criteria</span>}
                        {q.active && !q.enabled && <span className="ml-2 text-[11px] text-zinc-400">paused</span>}
                      </td>
                      <td className="px-5 py-2.5">{q.runs}</td>
                      <td className="px-5 py-2.5">{q.results}</td>
                      <td className="px-5 py-2.5">{q.new_jobs}</td>
                      <td className="px-5 py-2.5">{q.relevant_jobs}</td>
                      <td className="px-5 py-2.5">{q.yield_per_request ?? "—"}</td>
                      <td className="px-5 py-2.5 text-xs text-zinc-500">{q.interval_days > 1 ? `every ${q.interval_days} days` : "daily"}{q.last_run_at ? ` · last ${timeAgo(q.last_run_at)}` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card className="overflow-x-auto">
            <div className="px-5 pt-5">
              <SectionHead title="By wording (query lab)" />
            </div>
            {data.by_wording.length === 0 ? (
              <p className="px-5 pb-5 text-sm text-zinc-500">No requests yet.</p>
            ) : (
              <table className="w-full min-w-[34rem] text-left text-sm">
                <thead>
                  <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
                    {["Wording", "Requests", "Returned", "New", "Relevant", "Relevant / request"].map((h) => (
                      <th key={h} className="px-5 py-2 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 tabular-nums dark:divide-zinc-800">
                  {data.by_wording.map((w) => (
                    <tr key={w.variant}>
                      <td className="px-5 py-2.5 text-zinc-900 dark:text-zinc-100">{w.variant}</td>
                      <td className="px-5 py-2.5">{w.requests}</td>
                      <td className="px-5 py-2.5">{w.results}</td>
                      <td className="px-5 py-2.5">{w.new_jobs}</td>
                      <td className="px-5 py-2.5">{w.relevant_jobs}</td>
                      <td className="px-5 py-2.5">{w.relevant_per_request ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card className="overflow-x-auto">
            <div className="px-5 pt-5">
              <SectionHead title="Recent requests" />
            </div>
            {data.recent.length === 0 ? (
              <p className="px-5 pb-5 text-sm text-zinc-500">No requests yet.</p>
            ) : (
              <table className="w-full min-w-[38rem] text-left text-xs">
                <thead>
                  <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
                    {["When", "Search", "Sent", "Result"].map((h) => (
                      <th key={h} className="px-5 py-2 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {data.recent.map((c) => (
                    <tr key={c.id}>
                      <td className="px-5 py-2 whitespace-nowrap text-zinc-500" title={dateTime(c.at)}>
                        {timeAgo(c.at)}
                      </td>
                      <td className="px-5 py-2 text-zinc-800 dark:text-zinc-200">
                        {c.query ?? "—"}
                        {c.page > 1 && <span className="text-zinc-400"> · page {c.page}</span>}
                        {c.purpose !== "scan" && <span className="text-zinc-400"> · {c.purpose}</span>}
                        {c.variant && <span className="block text-[11px] text-zinc-400">{c.variant}</span>}
                      </td>
                      <td className="max-w-[18rem] truncate px-5 py-2 font-mono text-[11px] text-zinc-400" title={JSON.stringify(c.params)}>
                        {Object.entries(c.params)
                          .filter(([k]) => k !== "query")
                          .map(([k, v]) => `${k}=${v}`)
                          .join(" ")}
                      </td>
                      <td className="px-5 py-2 text-zinc-500">
                        {c.status === "ok" ? `${c.results} jobs · ${c.new_jobs} new · ${c.relevant_jobs} relevant` : c.status === "sending" ? "sent, no answer recorded" : <span className="text-rose-600/80 dark:text-rose-400/80">{c.error ?? "failed"}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          {loading && <p className="text-xs text-zinc-400">Updating…</p>}
        </div>
      )}
    </div>
  );
}
