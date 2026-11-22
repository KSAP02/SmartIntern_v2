// Scan Jobs → Scans and what they found: one row per scan, whatever sources it read. Opening a scan
// lists its requests grouped by source (JSearch, each company board system with its companies,
// remote feeds); opening a request shows the jobs it returned and what became of each.
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import type { ApiCallOut, CallExplainOut, CallJobOut, ScanPhase, ScanRequestsOut } from "../../lib/types";
import { cx, timeAgo } from "../../lib/util";
import { Badge, Card, ErrorBanner, Skeleton, Spinner } from "../ui";
import { PHASE_LABEL, dateTime, pct } from "./format";
import { RequestParams } from "./RequestParams";
import { ParamTable, PastRequests } from "./RequestExplain";

const OUTCOME: Record<string, string> = {
  new: "new",
  updated: "updated",
  unchanged: "already had",
  duplicate: "same job as another listing",
  already_seen: "seen before (discarded / deleted)",
  too_old: "too old, skipped",
};

function nowLabel(j: CallJobOut): string {
  if (j.job_id == null) return j.outcome === "too_old" ? "—" : "no longer kept";
  if (j.decision) return { selected: "Selected", applied: "Applied", discarded: "Discarded" }[j.decision] ?? j.decision;
  if (j.pipeline_status === "mapped" || j.pipeline_status === "relevant") return "In Matches";
  if (j.pipeline_status === "not_relevant") return "Not relevant";
  if (j.pipeline_status === "excluded") return "Excluded";
  return j.pipeline_status ?? "—";
}

function CallRow({ call, onOpenJob, nested = false }: { call: ApiCallOut; onOpenJob: (id: number) => void; nested?: boolean }) {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<CallJobOut[] | null>(null);
  const [why, setWhy] = useState<CallExplainOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !jobs) {
      try {
        const [j, w] = await Promise.all([api.callJobs(call.id), api.callExplain(call.id)]);
        setJobs(j);
        setWhy(w);
      } catch (e) {
        setError(errorMessage(e));
      }
    }
  };

  const filters = Object.entries(call.params)
    .filter(([k]) => !["query", "country", "page", "num_pages"].includes(k))
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${String(v).replace(/,/g, ", ").toLowerCase()}`)
    .join(" · ");

  return (
    <li>
      <button type="button" onClick={() => void toggle()} aria-expanded={open} className={cx("flex w-full items-start gap-2 py-2.5 pr-4 text-left hover:bg-zinc-100/60 dark:hover:bg-zinc-800/40", nested ? "pl-10" : "pl-4")}>
        {open ? <ChevronDown className="mt-0.5 size-4 shrink-0 text-zinc-400" /> : <ChevronRight className="mt-0.5 size-4 shrink-0 text-zinc-400" />}
        <div className="min-w-0 flex-1">
          <p className="text-sm text-zinc-900 dark:text-zinc-100">
            {call.source_kind === "board" ? String(call.params.company ?? call.query ?? "—") : `“${call.query ?? "—"}”`}{call.page > 1 && <span className="text-zinc-400"> · page {call.page}</span>}
            {call.purpose !== "scan" && <span className="text-zinc-400"> · {call.purpose}</span>}
            {call.variant && <span className="ml-2 text-[11px] text-zinc-400">{call.variant}</span>}
            {!nested && call.source_kind === "board" && <span className="ml-2 text-[11px] text-zinc-400">company board · free</span>}
            {!nested && call.source_kind === "feed" && <span className="ml-2 text-[11px] text-zinc-400">remote feed · free</span>}
          </p>
          {!(nested && call.source_kind !== "search") && (
            <p className="mt-0.5 text-xs text-zinc-500" title={dateTime(call.at)}>
              {timeAgo(call.at)}
              {filters && ` · ${filters}`}
            </p>
          )}
        </div>
        <span className="shrink-0 text-xs text-zinc-500 tabular-nums">
          {call.status === "ok"
            ? call.source_kind !== "search"
              ? `${call.results} listed · ${kept(call)} kept · ${call.new_jobs} new · ${call.relevant_jobs} relevant`
              : `${call.results} returned · ${call.new_jobs} new · ${call.relevant_jobs} relevant`
            : call.status === "sending"
              ? "no answer recorded"
              : <span className="text-rose-600/80 dark:text-rose-400/80">failed</span>}
        </span>
      </button>
      {open && (
        <div className={cx("border-t border-zinc-100 pt-2 pr-4 pb-4 dark:border-zinc-800", nested ? "pl-10" : "pl-4")}>
          {call.error && <p className="mb-2 text-xs text-rose-600/80 dark:text-rose-400/80">{call.error}</p>}
          {why && (why.findings.length > 0 || why.suggestions.length > 0) && (
            <div className="mb-3 text-xs">
              <p className="mb-1 text-[11px] font-semibold tracking-wider text-zinc-400 uppercase">Why these results</p>
              <ul className="list-disc space-y-0.5 pl-4 text-zinc-600 dark:text-zinc-400">
                {why.findings.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
              {why.suggestions.length > 0 && (
                <>
                  <p className="mt-2 mb-1 text-[11px] font-semibold tracking-wider text-zinc-400 uppercase">Next time</p>
                  <ul className="list-disc space-y-0.5 pl-4 text-zinc-800 dark:text-zinc-200">
                    {why.suggestions.map((x) => (
                      <li key={x}>{x}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
          <div className="mb-3 space-y-3 rounded-md bg-zinc-50 px-3 py-2.5 dark:bg-zinc-900">
            {why ? <ParamTable notes={why.params} /> : <RequestParams params={call.params} />}
            {why && <PastRequests items={why.history} title="Other requests for this search" />}
          </div>
          {error && <ErrorBanner message={error} />}
          {!jobs && !error && <Skeleton className="h-16" />}
          {jobs && jobs.length === 0 && <p className="text-xs text-zinc-500">No jobs recorded for this request.</p>}
          {jobs && jobs.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[36rem] text-left text-xs">
                <thead>
                  <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
                    <th className="py-2 pr-3 font-medium">#</th>
                    <th className="py-2 pr-3 font-medium">Job</th>
                    <th className="py-2 pr-3 font-medium">Title match</th>
                    <th className="py-2 pr-3 font-medium">This time</th>
                    <th className="py-2 font-medium">Now</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {jobs.map((j) => (
                    <tr key={j.position}>
                      <td className="py-2 pr-3 text-zinc-400 tabular-nums">{j.position}</td>
                      <td className="py-2 pr-3">
                        {j.job_id != null ? (
                          <button type="button" onClick={() => onOpenJob(j.job_id!)} className="text-left text-zinc-900 hover:text-violet-700 hover:underline dark:text-zinc-100 dark:hover:text-violet-300">
                            {j.title}
                          </button>
                        ) : (
                          <span className="text-zinc-700 dark:text-zinc-300">{j.title}</span>
                        )}
                        <span className="block text-[11px] text-zinc-400">{[j.company_name, j.location_text].filter(Boolean).join(" · ")}</span>
                      </td>
                      <td className="py-2 pr-3 text-zinc-500 tabular-nums">{j.role_score != null ? `${pct(j.role_score)} ${j.role_match ?? ""}` : "—"}</td>
                      <td className="py-2 pr-3 text-zinc-500">{OUTCOME[j.outcome] ?? j.outcome}</td>
                      <td className={cx("py-2", nowLabel(j) === "In Matches" || nowLabel(j) === "Selected" ? "text-zinc-900 dark:text-zinc-100" : "text-zinc-500")} title={j.status_reason ?? undefined}>
                        {nowLabel(j)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function kept(c: ApiCallOut): number {
  return c.source_kind === "search" ? c.results : Math.max(0, c.results - (c.skipped_scope ?? 0) - (c.skipped_title ?? 0));
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

interface Group {
  key: string;
  heading: string;
  note?: string;
  calls: ApiCallOut[];
}

/** A scan's requests by source: JSearch, then each company board system, then the remote feeds. */
function groups(calls: ApiCallOut[]): Group[] {
  const search = calls.filter((c) => c.source_kind === "search");
  const boards = new Map<string, ApiCallOut[]>();
  const feeds: ApiCallOut[] = [];
  for (const c of calls) {
    if (c.source_kind === "board") boards.set(c.api, [...(boards.get(c.api) ?? []), c]);
    else if (c.source_kind === "feed") feeds.push(c);
  }
  const out: Group[] = [];
  if (search.length) out.push({ key: "search", heading: "Job search · JSearch", calls: search });
  for (const [api, list] of boards) {
    const withJobs = list.filter((c) => c.status === "ok" && kept(c) > 0).length;
    out.push({
      key: api,
      heading: `${list[0].source_label ?? api} · company boards`,
      note: `${plural(list.length, "company", "companies")} · ${withJobs} with matching jobs`,
      // companies with matching jobs first, then the rest by name
      calls: [...list].sort((a, b) => kept(b) - kept(a) || String(a.params.company ?? "").localeCompare(String(b.params.company ?? ""))),
    });
  }
  if (feeds.length) out.push({ key: "feeds", heading: "Remote feeds · open to India", calls: feeds });
  return out;
}

function ScanRow({ scan, onOpenJob }: { scan: ScanRequestsOut; onOpenJob: (id: number) => void }) {
  const [open, setOpen] = useState(false);
  const calls = scan.calls;
  const n = (k: string) => calls.filter((c) => c.source_kind === k).length;
  const boardSystems = new Set(calls.filter((c) => c.source_kind === "board").map((c) => c.api)).size;
  const failed = calls.filter((c) => c.status === "error").length;
  const sum = (f: (c: ApiCallOut) => number) => calls.filter((c) => c.status === "ok").reduce((a, c) => a + f(c), 0);
  const parts = [
    n("search") > 0 && plural(n("search"), "JSearch request"),
    n("board") > 0 && `${plural(n("board"), "company", "companies")} on ${plural(boardSystems, "board system")}`,
    n("feed") > 0 && plural(n("feed"), "feed read"),
  ].filter(Boolean) as string[];
  const running = scan.phase !== "done" && scan.phase !== "failed";

  return (
    <li>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-start gap-2 px-4 py-3 text-left hover:bg-zinc-100/60 dark:hover:bg-zinc-800/40">
        {open ? <ChevronDown className="mt-0.5 size-4 shrink-0 text-zinc-400" /> : <ChevronRight className="mt-0.5 size-4 shrink-0 text-zinc-400" />}
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-zinc-900 dark:text-zinc-100">
            <span title={dateTime(scan.started_at)}>Scan · {timeAgo(scan.started_at)}</span>
            <Badge tone={scan.trigger === "auto" ? "neutral" : "accent"}>{scan.trigger === "auto" ? "automatic" : "manual"}</Badge>
            {running && (
              <span className="flex items-center gap-1.5 text-xs text-zinc-500">
                <Spinner className="size-3" /> {PHASE_LABEL[scan.phase as ScanPhase] ?? scan.phase}
              </span>
            )}
            {scan.phase === "failed" && (
              <span className="text-xs text-rose-600/80 dark:text-rose-400/80" title={scan.error ?? undefined}>
                Failed
              </span>
            )}
          </p>
          <p className="mt-0.5 text-xs text-zinc-500">
            {parts.join(" + ") || "Nothing read yet"}
            {failed > 0 && <span className="text-rose-600/80 dark:text-rose-400/80"> · {failed} failed</span>}
          </p>
        </div>
        <span className="shrink-0 text-xs text-zinc-500 tabular-nums">
          {sum((c) => c.results)} listed · {sum(kept)} kept · {sum((c) => c.new_jobs)} new · {sum((c) => c.relevant_jobs)} relevant
        </span>
      </button>
      {open && (
        <div className="border-t border-zinc-100 dark:border-zinc-800">
          {scan.error && <p className="px-10 pt-2 text-xs text-rose-600/80 dark:text-rose-400/80">{scan.error}</p>}
          {groups(calls).map((g) => (
            <div key={g.key}>
              <p className="flex flex-wrap items-baseline gap-x-2 bg-zinc-50 py-1.5 pr-4 pl-10 dark:bg-zinc-900">
                <span className="text-[11px] font-semibold tracking-wider text-zinc-500 uppercase">{g.heading}</span>
                {g.note && <span className="text-[11px] text-zinc-400">{g.note}</span>}
              </p>
              <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {g.calls.map((c) => (
                  <CallRow key={c.id} call={c} onOpenJob={onOpenJob} nested />
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </li>
  );
}

export function RequestResults({ scans, error, onRetry, onOpenJob }: { scans: ScanRequestsOut[] | null; error: string | null; onRetry: () => void; onOpenJob: (id: number) => void }) {
  return (
    <div className="mb-8">
      <h2 className="mb-3 text-xs font-semibold tracking-wider text-zinc-400 uppercase">Scans and what they found</h2>
      {error && <ErrorBanner message={error} onRetry={onRetry} />}
      {!scans && !error && <Skeleton className="h-24" />}
      {scans && scans.length === 0 && (
        <Card className="px-4 py-5 text-sm text-zinc-500">No scans yet. Each Scan now (or automatic scan) shows up here with every source it read and the jobs they returned.</Card>
      )}
      {scans && scans.length > 0 && (
        <Card>
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {scans.map((s) =>
              s.scan_id ? <ScanRow key={s.scan_id} scan={s} onOpenJob={onOpenJob} /> : s.calls.map((c) => <CallRow key={c.id} call={c} onOpenJob={onOpenJob} />),
            )}
          </ul>
        </Card>
      )}
    </div>
  );
}
