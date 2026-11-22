import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ArrowUpRight, Check, ChevronDown, ChevronRight, ExternalLink, Plus, RotateCcw, Send, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import type { FactSource, JobCard, JobDecision, JobDetail, RequirementOut } from "../../lib/types";
import { cx } from "../../lib/util";
import { Badge, Button, ErrorBanner, Skeleton } from "../ui";
import { Modal } from "../Modal";
import { useToast } from "../Toast";
import { applyRoute, CATEGORY_LABEL, dateTime, formatPay, foundAgo, pct, SENIORITY_LABEL, WORKPLACE_LABEL } from "./format";
import { MiniBar } from "./ToggleChips";
import { AddRoleModal } from "./AddRole";

const SOURCE_BADGE: Record<FactSource, string> = { source: "from source", rules: "from rules", ai: "from AI" };

type Status = NonNullable<RequirementOut["status"]> | "unknown";

/** met = clay filled, partial = clay half, missing = muted red, unknown = gray. */
export function StatusDot({ status }: { status: RequirementOut["status"] }) {
  const s: Status = status ?? "unknown";
  const label = { met: "Met", partial: "Partly met", missing: "Missing", unknown: "Not assessed" }[s];
  return (
    <span title={label} aria-label={label} role="img" className="mt-1.5 inline-flex size-2.5 shrink-0">
      {s === "met" && <span className="size-2.5 rounded-full bg-violet-600 dark:bg-violet-400" />}
      {s === "partial" && (
        <span className="flex size-2.5 overflow-hidden rounded-full border border-violet-600 dark:border-violet-400">
          <span className="h-full w-1/2 bg-violet-600 dark:bg-violet-400" />
        </span>
      )}
      {s === "missing" && <span className="size-2.5 rounded-full bg-rose-400/80 dark:bg-rose-400/70" />}
      {s === "unknown" && <span className="size-2.5 rounded-full bg-zinc-300 dark:bg-zinc-600" />}
    </span>
  );
}

function Fact({ label, children, src }: { label: string; children: ReactNode; src?: FactSource }) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1.5 text-[11px] text-zinc-400 dark:text-zinc-500">
        {label}
        {src && <span className="text-[10px] text-zinc-400 italic dark:text-zinc-500">{SOURCE_BADGE[src]}</span>}
      </dt>
      <dd className="mt-0.5 text-sm break-words text-zinc-800 dark:text-zinc-200">{children}</dd>
    </div>
  );
}

function Requirement({ r }: { r: RequirementOut }) {
  const [open, setOpen] = useState(false);
  const canOpen = r.evidence.length > 0;
  return (
    <li className="border-b border-zinc-100 py-3 last:border-b-0 dark:border-zinc-800">
      <div className="flex gap-2.5">
        <StatusDot status={r.status} />
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-snug text-zinc-800 dark:text-zinc-200">{r.text}</p>
          {r.skills.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {r.skills.map((s) => (
                <Badge key={s}>{s}</Badge>
              ))}
            </div>
          )}
          {r.best && (
            <button
              type="button"
              disabled={!canOpen}
              aria-expanded={canOpen ? open : undefined}
              onClick={() => setOpen((o) => !o)}
              className="mt-2 flex w-full items-center gap-2 text-left text-xs text-zinc-500 disabled:cursor-default dark:text-zinc-400"
            >
              {canOpen && (open ? <ChevronDown className="size-3 shrink-0" /> : <ChevronRight className="size-3 shrink-0" />)}
              <span className="min-w-0 truncate">{r.best.title}</span>
              <MiniBar value={r.best.score * 100} className="ml-auto shrink-0" />
              <span className="w-8 shrink-0 text-right tabular-nums">{pct(r.best.score)}</span>
            </button>
          )}
          {open && (
            <ul className="mt-2 space-y-1 border-l border-zinc-200 pl-3 dark:border-zinc-800">
              {r.evidence.map((e) => (
                <li key={e.card_id} className="flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
                  <span className="min-w-0 truncate">{e.title}</span>
                  <MiniBar value={e.score * 100} className="ml-auto shrink-0" />
                  <span className="w-8 shrink-0 text-right tabular-nums">{pct(e.score)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </li>
  );
}

const GROUPS: { key: RequirementOut["importance"]; label: string }[] = [
  { key: "must", label: "Must-have" },
  { key: "nice", label: "Nice-to-have" },
  { key: "unknown", label: "Other" },
];

function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="mb-2 text-xs font-semibold tracking-wider text-zinc-400 uppercase">{children}</h3>;
}

/** Right-side drawer with one job's facts, evidence map and description. */
const ROUTE_HINT: Record<string, string> = {
  form: "a company application form with no account needed: the agent will be able to fill it in.",
  direct: "the employer's own site; the form isn't known yet.",
  account: "this company's hiring system makes you create an account first.",
  aggregator: "a job board that sends you on to the real posting.",
  platform: "a site that needs your login; you apply there yourself.",
};

/** How this job can be applied to (Phase 2.7 apply route). */
function ApplyRouteLine({ route, url }: { route: string | null; url: string | null }) {
  const r = applyRoute(route);
  if (!r) return null;
  return (
    <p className="text-sm text-zinc-600 dark:text-zinc-400">
      <span className={r.kind === "form" ? "font-medium text-emerald-700 dark:text-emerald-400" : "font-medium text-zinc-900 dark:text-zinc-100"}>{r.label}</span>: {ROUTE_HINT[r.kind] ?? ""}
      {url && (
        <>
          {" "}
          <a href={url} target="_blank" rel="noopener noreferrer" className="text-violet-700 hover:underline dark:text-violet-300">
            Open
          </a>
        </>
      )}
    </p>
  );
}

export function JobDetailPanel({ jobId, onClose, onChanged }: { jobId: number | null; onClose: () => void; onChanged: (j: JobCard) => void }) {
  const toast = useToast();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [addingRole, setAddingRole] = useState(false);

  const load = async (id: number) => {
    setError(null);
    try {
      setJob(await api.getJob(id));
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  useEffect(() => {
    setJob(null);
    if (jobId !== null) void load(jobId);
  }, [jobId]);

  const setRelevance = async (override: "relevant" | "not_relevant" | null) => {
    if (!job) return;
    setBusy(true);
    try {
      const c = await api.setRelevance(job.id, override);
      onChanged(c);
      await load(job.id);
      toast.success(override === "relevant" ? "Moved to your matches" : override === "not_relevant" ? "Marked not relevant" : "The checks decide again");
    } catch (e) {
      toast.error("Couldn't update", errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const decide = async (decision: JobDecision | null) => {
    if (!job) return;
    setBusy(true);
    try {
      const c = await api.patchJob(job.id, { decision });
      setJob({ ...job, ...c });
      onChanged(c);
      toast.success(
        decision === "selected" ? "Selected: the agent will apply to it" : decision === "discarded" ? "Discarded" : decision === "applied" ? "Marked as applied" : "Back to undecided",
      );
    } catch (e) {
      toast.error("Couldn't update job", errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const fs = job?.field_sources ?? {};
  const pay = job ? formatPay(job) : null;
  const cov = job?.coverage;

  return (
    <Modal
      side
      open={jobId !== null}
      onClose={onClose}
      title={job?.title ?? (error ? "Job" : "Loading…")}
      subtitle={job ? [job.company_name, job.location_text].filter(Boolean).join(" · ") || undefined : undefined}
    >
      {error && <ErrorBanner message={error} onRetry={() => jobId !== null && void load(jobId)} />}
      {!job && !error && (
        <div className="space-y-3">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-24" />
          <Skeleton className="h-40" />
        </div>
      )}
      {job && (
        <div className="space-y-7">
          <ApplyRouteLine route={job.apply_route} url={job.apply_route_url} />
          <div className="flex flex-wrap items-center gap-2">
            {job.job_url && (
              <a href={job.job_url} target="_blank" rel="noopener noreferrer">
                <Button size="sm" icon={<ExternalLink className="size-3.5" />}>
                  Original posting
                </Button>
              </a>
            )}
            {job.apply_url && job.apply_url !== job.job_url && (
              <a href={job.apply_url} target="_blank" rel="noopener noreferrer">
                <Button size="sm" variant="primary" icon={<Send className="size-3.5" />}>
                  Apply
                </Button>
              </a>
            )}
            {!job.decision && (
              <>
                <Button size="sm" loading={busy} icon={<Check className="size-3.5" />} onClick={() => void decide("selected")}>
                  Select for applying
                </Button>
                <Button size="sm" variant="ghost" disabled={busy} icon={<X className="size-3.5" />} onClick={() => void decide("discarded")}>
                  Discard
                </Button>
              </>
            )}
            {job.decision === "selected" && (
              <Button size="sm" loading={busy} onClick={() => void decide("applied")}>
                Mark applied
              </Button>
            )}
            {job.decision && (
              <Button size="sm" variant="ghost" disabled={busy} icon={<RotateCcw className="size-3.5" />} onClick={() => void decide(null)}>
                {job.decision === "discarded" ? "Restore" : "Undo"}
              </Button>
            )}
            {job.decision ? (
              <Badge tone={job.decision === "selected" ? "accent" : "neutral"}>{job.decision === "selected" ? "Selected" : job.decision === "applied" ? "Applied" : "Discarded"}</Badge>
            ) : job.pipeline_status === "mapped" || job.pipeline_status === "relevant" ? (
              job.fits_preset ? <Badge tone="accent">Fits your preset</Badge> : <Badge>Other relevant</Badge>
            ) : (
              <Badge>{job.pipeline_status === "excluded" ? "Excluded" : "Not relevant"}</Badge>
            )}
            {job.expired && <Badge>Expired</Badge>}
          </div>

          {job.status_reason && (job.pipeline_status === "excluded" || job.pipeline_status === "not_relevant") && (
            <p className="-mt-4 text-xs text-zinc-500 dark:text-zinc-400">{job.status_reason}</p>
          )}

          <div className="-mt-3 flex flex-wrap items-center gap-2">
            {job.pipeline_status === "not_relevant" || job.pipeline_status === "excluded" ? (
              <Button size="sm" icon={<ArrowUpRight className="size-3.5" />} loading={busy} onClick={() => void setRelevance("relevant")}>
                Move to matches
              </Button>
            ) : (
              !job.relevance_override && (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => void setRelevance("not_relevant")}>
                  Not relevant
                </Button>
              )
            )}
            {job.relevance_override && (
              <>
                <span className="text-xs text-zinc-500">{job.relevance_override === "relevant" ? "You moved this to your matches." : "You marked this not relevant."}</span>
                <Button size="sm" variant="ghost" disabled={busy} icon={<RotateCcw className="size-3.5" />} onClick={() => void setRelevance(null)}>
                  Let the checks decide
                </Button>
              </>
            )}
            <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={() => setAddingRole(true)}>
              Add title to my roles
            </Button>
          </div>
          <AddRoleModal title={job.title} open={addingRole} onClose={() => setAddingRole(false)} onAdded={() => window.setTimeout(() => void load(job.id), 1500)} />

          {!job.fits_preset && job.preset_misses.length > 0 && (
            <p className="-mt-4 text-xs text-zinc-500 dark:text-zinc-400">Outside your preset: {job.preset_misses.join(" · ")}</p>
          )}

          <section>
            <SectionTitle>Facts</SectionTitle>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
              <Fact label="Job type" src={fs.category}>
                {job.category ? CATEGORY_LABEL[job.category] : "Unknown"}
              </Fact>
              <Fact label="Workplace" src={fs.workplace_type}>
                {job.workplace_type ? WORKPLACE_LABEL[job.workplace_type] : "Unknown"}
              </Fact>
              <Fact label="Countries" src={fs.country_codes}>
                {job.country_codes.length ? job.country_codes.join(", ") : "Unknown"}
              </Fact>
              {job.remote_regions.length > 0 && (
                <Fact label="Remote from" src={fs.remote_regions}>
                  {job.remote_regions.join(", ")}
                </Fact>
              )}
              <Fact label="Pay" src={fs.salary_min ?? fs.compensation_type}>
                {pay ?? "Unknown"}
              </Fact>
              <Fact label="Seniority" src={fs.seniority}>
                {job.seniority ? SENIORITY_LABEL[job.seniority] : "Unknown"}
              </Fact>
              {job.min_years_experience != null && (
                <Fact label="Experience asked" src={fs.min_years_experience}>
                  {job.min_years_experience}+ years
                </Fact>
              )}
              {job.internship_duration && (
                <Fact label="Internship length" src={fs.internship_duration}>
                  {job.internship_duration}
                </Fact>
              )}
              {job.visa_sponsorship && (
                <Fact label="Visa sponsorship" src={fs.visa_sponsorship}>
                  {job.visa_sponsorship === "yes" ? "Offered" : "Not offered"}
                </Fact>
              )}
              {job.start_date && (
                <Fact label="Start" src={fs.start_date}>
                  {job.start_date}
                </Fact>
              )}
              {job.apply_deadline && (
                <Fact label="Apply by" src={fs.apply_deadline}>
                  {job.apply_deadline}
                </Fact>
              )}
              {job.source_published_at && <Fact label="Posted">{dateTime(job.source_published_at)}</Fact>}
              <Fact label="Found">{foundAgo(job.first_seen_at)}</Fact>
              <Fact label="Seen on">
                {job.seen_on.map((s, i) => (
                  <span key={s.source}>
                    {i > 0 && ", "}
                    {s.job_url ? (
                      <a href={s.job_url} target="_blank" rel="noopener noreferrer" className="hover:text-violet-700 hover:underline dark:hover:text-violet-300">
                        {s.label ?? s.source}
                      </a>
                    ) : (
                      (s.label ?? s.source)
                    )}
                  </span>
                ))}
              </Fact>
              {job.role_score != null && (
                <Fact label="Role match">
                  <span>{pct(job.role_score)}</span>
                  {job.role_match && <span className="block truncate text-xs text-zinc-500">{job.role_match}</span>}
                </Fact>
              )}
              <Fact label="Role context match">
                <span title="This job's text vs the role context of its closest role (Memory ▾ Role contexts)">{job.relevance != null ? pct(job.relevance) : "—"}</span>
                {job.relevance == null && <span className="block truncate text-xs text-zinc-500">no context for this role yet</span>}
              </Fact>
            </dl>
            {job.tags.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1">
                {job.tags.map((t) => (
                  <Badge key={t}>{t}</Badge>
                ))}
              </div>
            )}
          </section>

          <section>
            <SectionTitle>Coverage</SectionTitle>
            {cov && cov.must_total + cov.nice_total > 0 ? (
              <div className="space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
                {cov.must_total > 0 && (
                  <div className="flex items-center gap-3">
                    <span className="tabular-nums">
                      {cov.must_met}/{cov.must_total} must-haves met
                      {cov.must_partial > 0 && <span className="text-zinc-500"> · {cov.must_partial} partly</span>}
                      {cov.must_missing > 0 && <span className="text-zinc-500"> · {cov.must_missing} missing</span>}
                    </span>
                    {cov.fit != null && (
                      <span className="ml-auto flex items-center gap-2 text-xs text-zinc-500">
                        <MiniBar value={cov.fit} className="w-20" />
                        <span className="tabular-nums">{cov.fit}% fit</span>
                      </span>
                    )}
                  </div>
                )}
                {cov.nice_total > 0 && (
                  <p className="text-xs text-zinc-500">
                    {cov.nice_met}/{cov.nice_total} nice-to-haves met
                  </p>
                )}
              </div>
            ) : (
              <p className="text-sm text-zinc-500">No requirements were found in this posting.</p>
            )}
          </section>

          {job.snippet_only && (
            <p className="rounded-md border border-zinc-200 px-3 py-2 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
              This source shares only a short excerpt of the description, so the requirements below are incomplete. Open the posting for the full text.
            </p>
          )}

          {job.requirements.length > 0 && (
            <section>
              <SectionTitle>Requirements ↔ your evidence</SectionTitle>
              <div className="space-y-4">
                {GROUPS.map((g) => {
                  const rs = job.requirements.filter((r) => r.importance === g.key);
                  if (!rs.length) return null;
                  return (
                    <div key={g.key}>
                      <p className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                        {g.label} <span className="text-zinc-400">({rs.length})</span>
                      </p>
                      <ul>
                        {rs.map((r) => (
                          <Requirement key={r.id} r={r} />
                        ))}
                      </ul>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {(job.matched_skills.length > 0 || job.missing_skills.length > 0) && (
            <section className="space-y-3">
              {job.matched_skills.length > 0 && (
                <div>
                  <SectionTitle>Skills you have</SectionTitle>
                  <div className="flex flex-wrap gap-1">
                    {job.matched_skills.map((s) => (
                      <Badge key={s} tone="accent">
                        {s}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              {job.missing_skills.length > 0 && (
                <div>
                  <SectionTitle>Skills it asks for that your profile lacks</SectionTitle>
                  <div className="flex flex-wrap gap-1">
                    {job.missing_skills.map((s) => (
                      <Badge key={s}>{s}</Badge>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}

          <section>
            <SectionTitle>Description</SectionTitle>
            <div
              className={cx(
                "text-sm leading-relaxed break-words whitespace-pre-wrap text-zinc-700 dark:text-zinc-300",
                !job.description_text && "text-zinc-500",
              )}
            >
              {job.description_text || "No description."}
            </div>
          </section>
        </div>
      )}
    </Modal>
  );
}
