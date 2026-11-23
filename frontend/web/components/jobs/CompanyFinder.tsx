// Admin settings → Company finder (Phase 2.7 E; moved from Scan Jobs 2026-11-23; runs by itself
// since 2026-11-23, every run on the Admin → Company finder page): finds companies
// hiring in India and their job boards in the background (seed list of Indian companies, the YC
// list of companies in India, and the Common Crawl index files), keeping only boards with jobs in
// India. Startups and Indian board systems are checked first (2026-11-23). Kept companies are read by every
// scan. Run by hand for now (the button); automated later with the agent.
import { useState } from "react";
import { Link } from "react-router-dom";
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
const ORIGIN: Record<string, string> = { seed: "seed list", yc: "YC list", crawl: "web index" };

export function CompanyFinder({ embedded = false }: { embedded?: boolean }) {
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

  const button = f && f.enabled && (
    <Button size="sm" variant={embedded ? "primary" : "secondary"} onClick={() => void run()} loading={starting} disabled={f.running}>
      {f.running ? "Running…" : "Run now"}
    </Button>
  );
  const Box = embedded ? "div" : Card;
  return (
    <div className={embedded ? "" : "mb-8"}>
      {embedded ? (
        button && <div className="mb-3">{button}</div>
      ) : (
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-xs font-semibold tracking-wider text-zinc-400 uppercase">Company finder</h2>
          {button}
        </div>
      )}
      {finder.error && <ErrorBanner message={finder.error} onRetry={finder.reload} />}
      {!f && !finder.error && <Skeleton className="h-20" />}
      {f && (
        <Box className={embedded ? "" : "px-4 py-3"}>
          <p className="text-xs text-zinc-500">
            Finds companies hiring in India and their job boards: a list of Indian companies, Y Combinator companies in India, and every
            company board address in the free Common Crawl web index (startups of every size). Only boards with jobs in India (or remote jobs
            open to India) are kept; every scan after that reads them. Startups and Indian board systems (Keka, Darwinbox, Zoho Recruit) are
            checked first.{" "}
            {f.auto
              ? `Runs by itself while the app runs: one run after another while companies are waiting (${f.due_now.toLocaleString()} due now), then a look every few hours.`
              : "Automatic runs are off ([scout.search.finder] auto = false)."}{" "}
            Each run checks up to {f.board_checks_per_run ?? 500} companies whose board is known and {f.leads_per_run ?? 50} whose board has
            to be searched for. Free: public pages and boards only.{" "}
            <Link to="/company-finder" className="text-violet-700 hover:underline dark:text-violet-300">
              Every run and what it found
            </Link>
            {!f.enabled &&
              (f.server_allows
                ? " Switched off ([scout.search.finder] enabled = false)."
                : " Off on this server (COMPANY_FINDER=false): it runs on your local app; this one only reads the companies it found.")}
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
          {Object.keys(f.pending_by_origin ?? {}).length > 0 && (
            <p className="mt-1 text-xs text-zinc-500 tabular-nums">
              Waiting, by where they came from:{" "}
              {Object.entries(f.pending_by_origin)
                .map(([o, n]) => `${n} ${ORIGIN[o] ?? o}`)
                .join(" · ")}
            </p>
          )}
          {crawl && (crawl.collection || crawl.collections_done.length > 0) && (
            <p className="mt-1 text-xs text-zinc-500 tabular-nums">
              Web index:{" "}
              {crawl.collection ? `${crawl.collection}, ${crawlPages} of ${crawlTotal || "?"} blocks read` : `read ${crawl.collections_done.join(", ")}`} ·{" "}
              {crawl.leads} board addresses found
              {crawl.last_error && <span className="text-amber-700 dark:text-amber-400"> · stopped early ({crawl.last_error}); carries on next run</span>}
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
        </Box>
      )}
    </div>
  );
}
