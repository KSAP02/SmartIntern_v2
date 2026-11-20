// The exact parameters of one JSearch request (GET /search), as sent. The API key travels in a
// header and is never shown.
const ORDER = ["query", "country", "page", "num_pages", "date_posted", "employment_types", "work_from_home", "job_requirements", "exclude_job_publishers"];

const MEANING: Record<string, string> = {
  query: "the search text (Google-style)",
  country: "country code to search in",
  page: "which page of results",
  num_pages: "pages per request (1 = up to 10 jobs)",
  date_posted: "only jobs posted within (since this search last ran)",
  employment_types: "job types (from Job types)",
  work_from_home: "remote only (from Workplace)",
  job_requirements: "experience filter (from your years of experience)",
  exclude_job_publishers: "job boards to skip (Admin settings)",
};

export function RequestParams({ params, className }: { params: Record<string, unknown>; className?: string }) {
  const keys = Object.keys(params).sort((a, b) => {
    const ia = ORDER.indexOf(a);
    const ib = ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  return (
    <div className={className}>
      <p className="mb-1 font-mono text-[11px] text-zinc-400">GET /jsearch/search</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px]">
        {keys.map((k) => (
          <div key={k} className="contents" title={MEANING[k]}>
            <dt className="text-zinc-500">{k}</dt>
            <dd className="break-all text-zinc-800 dark:text-zinc-200">{String(params[k])}</dd>
          </div>
        ))}
      </dl>
      {!("job_requirements" in params) && <p className="mt-1 text-[11px] text-zinc-400">No experience filter sent (any experience).</p>}
    </div>
  );
}
