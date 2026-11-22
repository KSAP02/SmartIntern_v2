// Scan Jobs → Company finder (Phase 2.7 E): finds companies hiring in India and their job boards in
// the background (seed list of Indian companies + the Common Crawl index), keeping only boards
// with jobs in India. Kept companies are read by every scan.
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import type { FinderStatusOut } from "../../lib/types";
import { timeAgo, useResource } from "../../lib/util";
import { Button, Card, ErrorBanner, Skeleton, Spinner } from "../ui";
import { useToast } from "../Toast";

const STATUS: { key: string; label: string }[] = [
  { key: "kept", label: "kept (scans read them)" },
  { key: "pending", label: "waiting to be checked" },
  { key: "no_india_jobs", label: "no jobs in India" },
  { key: "no_board", label: "no board found" },
  { key: "error", label: "couldn't be read" },
];
const HOW: Record<string, string> = { careers_page: "careers page", guessed: "name tried", crawl: "web index" };

export function CompanyFinder() {
  const toast = useToast();
  const finder = useResource(api.finderStatus, { pollMs: 3000, shouldPoll: (f) => f.running });
  const [starting, setStarting] = useState(false);
  const [open, setOpen] = useState(false);
  const f: FinderStatusOut | null = finder.data;

  const run = async () => {
    setStarting(true);
    try {
      finder.setData(await api.runFinder());
      toast.info("Company finder started", "It runs in the background; kept companies are read by your next scan.");
    } catch (e) {
      toast.error("Couldn't start the finder", errorMessage(e));
    } finally {
      setStarting(false);
    }
  };

  const crawl = f?.crawl;
  const crawlPages = crawl ? crawl.hosts.reduce((a, h) => a + (Number(h.done) || 0), 0) : 0;
  const crawlTotal = crawl ? crawl.hosts.reduce((a, h) => a + (Number(h.pages) || 0), 0) : 0;

  return (
    <div className="mb-8">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-xs font-semibold tracking-wider text-zinc-400 uppercase">Company finder</h2>
        {f && f.enabled && (
          <Button size="sm" onClick={() => void run()} loading={starting} disabled={f.running}>
            {f.running ? "Running…" : "Find companies"}
          </Button>
        )}
      </div>
      {finder.error && <ErrorBanner message={finder.error} onRetry={finder.reload} />}
      {!f && !finder.error && <Skeleton className="h-20" />}
      {f && (
        <Card className="px-4 py-3">
          <p className="text-xs text-zinc-500">
            Finds companies hiring in India and their job boards (a list of Indian companies, and board addresses from the free Common Crawl web
            index). Only boards with jobs in India are kept; every scan then reads them. Free: public pages and boards only.
            {!f.enabled && " Switched off ([scout.search.finder] enabled = false)."}
          </p>
          <p className="mt-2 flex flex-wrap items-center gap-x-2 text-sm text-zinc-800 dark:text-zinc-200">
            {f.running && <Spinner className="size-3" />}
            {f.running ? f.message : f.finished_at ? `Last run ${timeAgo(f.finished_at)}: ${f.message ?? ""}` : "Not run yet"}
            {f.error && <span className="text-xs text-rose-600/80 dark:text-rose-400/80">{f.error}</span>}
          </p>
          <p className="mt-1 text-xs text-zinc-500 tabular-nums">
            {STATUS.filter((s) => f.by_status[s.key])
              .map((s) => `${f.by_status[s.key]} ${s.label}`)
              .join(" · ") || "No companies to check yet"}
          </p>
          {crawl && crawl.collection && (
            <p className="mt-1 text-xs text-zinc-500 tabular-nums">
              Web index {crawl.collection}: {crawlPages} of {crawlTotal || "?"} pages read · {crawl.leads} board addresses found
            </p>
          )}
          {f.kept.length > 0 && (
            <>
              <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="mt-2 flex items-center gap-1 text-xs text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">
                {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                Companies kept ({f.kept.length}{f.kept.length === 50 ? "+" : ""})
              </button>
              {open && (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full min-w-[30rem] text-left text-xs">
                    <thead>
                      <tr className="border-b border-zinc-200 text-[11px] text-zinc-400 dark:border-zinc-800">
                        <th className="py-1.5 pr-3 font-medium">Company</th>
                        <th className="py-1.5 pr-3 font-medium">Board</th>
                        <th className="py-1.5 pr-3 font-medium">Found via</th>
                        <th className="py-1.5 font-medium">Jobs: in India / matching your roles</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                      {f.kept.map((k) => (
                        <tr key={`${k.kind}-${k.name}`}>
                          <td className="py-1.5 pr-3 text-zinc-900 dark:text-zinc-100">{k.name}</td>
                          <td className="py-1.5 pr-3 text-zinc-500">{k.kind_label ?? k.kind}</td>
                          <td className="py-1.5 pr-3 text-zinc-500">{HOW[k.how ?? ""] ?? k.how ?? "—"}</td>
                          <td className="py-1.5 text-zinc-500 tabular-nums">
                            {k.india_jobs ?? "—"} / {k.matching_jobs ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </Card>
      )}
    </div>
  );
}
