// JSearch search plan + request budget: what the next scan will send, and what it costs.
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import type { QueryOut, QuotaOut, SearchPlanOut } from "../../lib/types";
import { cx, timeAgo } from "../../lib/util";
import { Button, ErrorBanner, Skeleton } from "../ui";
import { dateTime } from "./format";

/** Request budget at a glance: month used / limit, today's share, reset date. */
export function QuotaMeter({ q, compact }: { q: QuotaOut; compact?: boolean }) {
  const usable = Math.max(1, q.monthly_limit);
  const used = Math.min(q.month_used, usable);
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs text-zinc-500 dark:text-zinc-400">
        <span>
          <span className="text-sm font-medium text-zinc-900 tabular-nums dark:text-zinc-100">{q.month_used}</span> / {q.monthly_limit} JSearch requests this month
          {q.reserve > 0 && <span> · {q.reserve} reserved for tests</span>}
        </span>
        <span>resets {q.resets_on}</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800" role="meter" aria-valuemin={0} aria-valuemax={usable} aria-valuenow={used} aria-label="Requests used this month">
        <div className={cx("h-full rounded-full", used / usable > 0.9 ? "bg-rose-500/80" : "bg-violet-600 dark:bg-violet-400")} style={{ width: `${(used / usable) * 100}%` }} />
      </div>
      {!compact && (
        <p className="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">
          {q.blocked_until
            ? `Paused after a "too many requests" reply until ${dateTime(q.blocked_until)}.`
            : `Today: ${q.today_used} used · ${q.today_allowance} more allowed · next scan spends at most ${q.scan_allowance}. One request = up to 10 jobs.`}
        </p>
      )}
    </div>
  );
}

function paramChips(params: Record<string, string | number>): string[] {
  const out: string[] = [];
  if (params.employment_types) out.push(String(params.employment_types).toLowerCase().replace(/,/g, ", "));
  if (params.work_from_home) out.push("remote only");
  if (params.job_requirements) out.push(String(params.job_requirements).includes("under_3") ? "under 3 yrs" : "no experience");
  else out.push("any experience");
  if (params.date_posted) out.push(`posted: ${String(params.date_posted).replace("3days", "3 days")}`);
  if (params.exclude_job_publishers) out.push(`not ${params.exclude_job_publishers}`);
  return out;
}

function YieldCell({ q }: { q: QueryOut }) {
  if (!q.runs) return <span className="text-zinc-400">not run yet</span>;
  return (
    <span title={`${q.results} returned · ${q.new_jobs} new · ${q.relevant_jobs} relevant over ${q.runs} requests`}>
      {q.yield_per_request ?? 0} relevant / request
    </span>
  );
}

/** The plan card (Search Settings). Building it calls nothing: it's a dry run. */
export function SearchPlan({ plan, error, loading, reload }: {
  plan: SearchPlanOut | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}) {
  if (error) return <ErrorBanner message={error} onRetry={reload} />;
  if (!plan) return <Skeleton className="h-40" />;
  const planned = new Set(plan.calls.map((c) => c.query_id));
  return (
    <div className="space-y-4">
      <QuotaMeter q={plan.quota} />

      {plan.notes.map((n) => (
        <p key={n} className="text-xs text-amber-700 dark:text-amber-400">
          {n}
        </p>
      ))}

      <div>
        <p className="mb-2 text-xs font-medium text-zinc-600 dark:text-zinc-400">
          Next automatic scan ({{ rotate: "rotate", each: "each role", combined: "combined OR", separate: "separate" }[plan.mode]}) sends {plan.calls.length} request{plan.calls.length === 1 ? "" : "s"}
          {plan.calls.length > 0 && " (a 2nd page only if page 1 is full and mostly new)"}
        </p>
        {plan.calls.length > 0 ? (
          <ul className="divide-y divide-zinc-100 rounded-md border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
            {plan.calls.map((c) => (
              <li key={`${c.query_id}-${c.page}`} className="px-3 py-2.5">
                <p className="text-sm text-zinc-900 dark:text-zinc-100">“{c.query}”</p>
                <p className="mt-0.5 text-xs text-zinc-500">
                  {[...paramChips(c.params), c.reason].join(" · ")}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-zinc-500">Nothing to send right now.</p>
        )}
      </div>

      {plan.queries.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium text-zinc-600 dark:text-zinc-400">Your searches (one per role × place, plus any combined OR searches you ran)</p>
          <div className="overflow-x-auto rounded-md border border-zinc-200 dark:border-zinc-800">
            <table className="w-full min-w-[34rem] text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
                  <th className="px-3 py-2 font-medium">Search</th>
                  <th className="px-3 py-2 font-medium">Yield</th>
                  <th className="px-3 py-2 font-medium">Next</th>

                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {plan.queries.map((q) => (
                  <tr key={q.id} className={cx(!q.enabled && "opacity-55")}>
                    <td className="px-3 py-2.5 text-zinc-900 dark:text-zinc-100">
                      {q.query}
                      {q.interval_days > 1 && <span className="ml-2 text-[11px] text-zinc-400">every {q.interval_days} days (nothing new lately)</span>}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-zinc-500">
                      <YieldCell q={q} />
                    </td>
                    <td className="px-3 py-2.5 text-xs text-zinc-500">
                      {planned.has(q.id) ? "next scan" : q.next_due_at ? dateTime(q.next_due_at) : "waiting for budget"}
                      {q.last_run_at && <span className="block text-[11px] text-zinc-400">ran {timeAgo(q.last_run_at)}</span>}
                    </td>

                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-zinc-500">
        <span>
          Budget rules are in{" "}
          <Link to="/admin#sources" className="text-violet-700 hover:underline dark:text-violet-300">
            Admin settings → JSearch
          </Link>
          .
        </span>
        <Button size="sm" variant="ghost" icon={<RefreshCw className="size-3.5" />} loading={loading} onClick={reload}>
          Dry run again
        </Button>
      </div>
    </div>
  );
}
