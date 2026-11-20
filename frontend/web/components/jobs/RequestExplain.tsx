// A JSearch request in plain words: each parameter as sent and what Google for Jobs does with it,
// what the same search returned before, and what we check on the jobs that come back.
import type { ParamNote, PastRequest } from "../../lib/types";
import { cx } from "../../lib/util";
import { dateTime } from "./format";

export function ParamTable({ notes, className }: { notes: ParamNote[]; className?: string }) {
  return (
    <div className={className}>
      <p className="mb-1.5 font-mono text-[11px] text-zinc-400">GET /jsearch/search (the API key travels in a header and is never shown)</p>
      <ul className="space-y-1.5">
        {notes.map((p) => (
          <li key={p.key} className="grid grid-cols-[9.5rem_1fr] gap-x-3 max-sm:grid-cols-1">
            <span className="font-mono text-[11px] text-zinc-500">
              {p.key}
              {p.narrows && <span className={cx("ml-1.5 font-sans text-[10px]", p.warn ? "text-amber-700 dark:text-amber-400" : "text-zinc-400")}>narrows</span>}
            </span>
            <span>
              <span className="font-mono text-[11px] break-all text-zinc-800 dark:text-zinc-200">{p.value}</span>
              {p.source && <span className="block text-[11px] leading-snug text-zinc-700 dark:text-zinc-300">From: {p.source}</span>}
              {p.meaning && <span className={cx("block text-[11px] leading-snug", p.warn ? "text-amber-700 dark:text-amber-400" : "text-zinc-500")}>{p.meaning}</span>}
            </span>
          </li>
        ))}
      </ul>
      {!notes.some((p) => p.key === "job_requirements") && <p className="mt-1.5 text-[11px] text-zinc-400">No experience filter sent: Google doesn't filter by experience; we drop jobs asking for more years than yours afterwards.</p>}
    </div>
  );
}

export function PastRequests({ items, title = "This search before" }: { items: PastRequest[]; title?: string }) {
  if (!items.length) return null;
  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold tracking-wider text-zinc-400 uppercase">{title}</p>
      <ul className="space-y-1 text-[11px]">
        {items.map((h) => (
          <li key={h.id} className="text-zinc-600 dark:text-zinc-400">
            <span className="text-zinc-400" title={dateTime(h.at)}>
              {new Date(h.at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}
            </span>{" "}
            <span className="text-zinc-800 dark:text-zinc-200">“{h.query}”</span> · <span className="tabular-nums">{h.results} returned · {h.relevant} relevant</span>
            <span className="block text-zinc-400">{h.differs.length ? `Then: ${h.differs.join(" · ")}` : "Same parameters as now"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AfterChecks({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold tracking-wider text-zinc-400 uppercase">Then, on the jobs that come back</p>
      <ol className="list-decimal space-y-0.5 pl-4 text-[11px] text-zinc-600 dark:text-zinc-400">
        {items.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ol>
    </div>
  );
}
