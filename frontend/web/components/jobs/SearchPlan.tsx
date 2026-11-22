// JSearch search plan + request budget: what the next scan will send, and what it costs.
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import type { QuotaOut, SearchPlanOut } from "../../lib/types";
import { cx } from "../../lib/util";
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
  if (params.date_posted) out.push(`posted: ${String(params.date_posted).replace("3days", "3 days")}`);
  if (params.exclude_job_publishers) out.push(`not ${params.exclude_job_publishers}`);
  return out;
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
          Next automatic scan sends {plan.calls.length} request{plan.calls.length === 1 ? "" : "s"}
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
