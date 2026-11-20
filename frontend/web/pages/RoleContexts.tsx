// Memory ▾ Role contexts (Phase 2.6): one job-description-style context per role in "Roles you
// want", written by the AI model from your memory cards when the role is added. Fetched jobs
// are compared with their role's context. View how it was drafted, edit, save, regenerate.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Brain, FlaskConical, Pencil, RefreshCw } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import type { RoleContextOut, RoleMatch } from "../lib/types";
import { cx, timeAgo, useResource } from "../lib/util";
import { Badge, Button, Card, EmptyState, ErrorBanner, PageHeader, Skeleton, Spinner, Textarea } from "../components/ui";
import { ChipInput } from "../components/ChipInput";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { pct } from "../components/jobs/format";

const LISTS = [
  { key: "responsibilities", label: "Responsibilities" },
  { key: "requirements", label: "Requirements" },
  { key: "nice_to_have", label: "Nice to have" },
] as const;
type ListKey = (typeof LISTS)[number]["key"];

interface Draft {
  summary: string;
  responsibilities: string;
  requirements: string;
  nice_to_have: string;
  search_titles: string[];
  keywords: string[];
}

const toDraft = (r: RoleContextOut): Draft => ({
  summary: r.summary,
  responsibilities: r.responsibilities.join("\n"),
  requirements: r.requirements.join("\n"),
  nice_to_have: r.nice_to_have.join("\n"),
  search_titles: r.search_titles,
  keywords: r.keywords,
});
const lines = (t: string) => t.split("\n").map((x) => x.trim()).filter(Boolean);

function StatusDot({ r }: { r: RoleContextOut }) {
  if (r.status === "ready") return <span className="inline-block size-1.5 rounded-full bg-emerald-500" title="Written" />;
  if (r.status === "failed") return <span className="inline-block size-1.5 rounded-full bg-rose-500" title="Writing failed" />;
  return <Spinner className="size-3" />;
}

function ContextView({ r, onSaved, onRegenerated }: { r: RoleContextOut; onSaved: (r: RoleContextOut) => void; onRegenerated: (r: RoleContextOut) => void }) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => toDraft(r));
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [showText, setShowText] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(toDraft(r));
  }, [r, editing]);

  const save = async () => {
    if (r.id == null) return;
    setSaving(true);
    try {
      const out = await api.patchRoleContext(r.id, {
        summary: draft.summary,
        responsibilities: lines(draft.responsibilities),
        requirements: lines(draft.requirements),
        nice_to_have: lines(draft.nice_to_have),
        search_titles: draft.search_titles,
        keywords: draft.keywords,
      });
      onSaved(out);
      setEditing(false);
      toast.success("Role context saved", "Jobs are being re-scored against it.");
    } catch (e) {
      toast.error("Couldn't save", errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const regenerate = async () => {
    if (r.id == null) return;
    setConfirm(false);
    setRegenerating(true);
    try {
      onRegenerated(await api.regenerateRoleContext(r.id));
      setEditing(false);
      toast.success("Role context rewritten", "Written from your current cards; jobs are being re-scored.");
    } catch (e) {
      toast.error("Couldn't regenerate", errorMessage(e));
    } finally {
      setRegenerating(false);
    }
  };

  if (r.status !== "ready" && r.status !== "failed") {
    return (
      <Card className="flex items-center gap-3 px-5 py-6 text-sm text-zinc-600 dark:text-zinc-400">
        <Spinner className="size-4" /> Writing the context for “{r.role}” from your memory cards… (about half a minute)
      </Card>
    );
  }

  return (
    <Card className="p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-serif text-xl text-zinc-900 dark:text-zinc-50">{r.role}</h2>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500">
            {r.edited && <Badge>edited by you</Badge>}
            {!r.in_roles && <Badge>role removed</Badge>}
            {r.memory_changed && <Badge tone="amber">your memory changed since</Badge>}
            {r.generated_at && <span>written {timeAgo(r.generated_at)}{r.model ? ` by ${r.model}` : ""}</span>}
            {r.edited && r.updated_at && <span>· edited {timeAgo(r.updated_at)}</span>}
          </div>
        </div>
        {!editing && (
          <div className="flex shrink-0 gap-2">
            {r.status === "ready" && (
              <Button size="sm" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(true)}>
                Edit
              </Button>
            )}
            <Button size="sm" icon={<RefreshCw className="size-3.5" />} loading={regenerating} onClick={() => (r.edited ? setConfirm(true) : void regenerate())}>
              Regenerate
            </Button>
          </div>
        )}
      </div>

      {r.status === "failed" && <p className="mb-4 text-sm text-rose-600/80 dark:text-rose-400/80">Writing failed: {r.error ?? "unknown error"}. Try Regenerate.</p>}

      {r.status === "ready" &&
        (editing ? (
          <div className="space-y-4">
            <div>
              <p className="mb-1 text-xs font-medium text-zinc-500">Summary</p>
              <Textarea rows={3} value={draft.summary} onChange={(e) => setDraft({ ...draft, summary: e.target.value })} />
            </div>
            {LISTS.map(({ key, label }) => (
              <div key={key}>
                <p className="mb-1 text-xs font-medium text-zinc-500">{label} <span className="font-normal text-zinc-400">(one per line)</span></p>
                <Textarea rows={Math.max(3, lines(draft[key as ListKey]).length + 1)} value={draft[key as ListKey]} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
              </div>
            ))}
            <div>
              <p className="mb-1 text-xs font-medium text-zinc-500">Search titles <span className="font-normal text-zinc-400">(used to word searches; not compared with jobs)</span></p>
              <ChipInput value={draft.search_titles} onChange={(search_titles) => setDraft({ ...draft, search_titles })} placeholder="e.g. Machine Learning Engineer — press Enter" />
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-zinc-500">Keywords <span className="font-normal text-zinc-400">(the first one is added with the “titles + keyword” wording)</span></p>
              <ChipInput value={draft.keywords} onChange={(keywords) => setDraft({ ...draft, keywords })} placeholder="e.g. Python — press Enter" />
            </div>
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
              <Button size="sm" variant="primary" loading={saving} onClick={() => void save()}>
                Save
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-5 text-sm">
            <p className="leading-relaxed text-zinc-700 dark:text-zinc-300">{r.summary}</p>
            {LISTS.map(({ key, label }) =>
              r[key].length ? (
                <div key={key}>
                  <h3 className="mb-1.5 text-xs font-semibold tracking-wider text-zinc-400 uppercase">{label}</h3>
                  <ul className="list-disc space-y-1 pl-5 text-zinc-700 dark:text-zinc-300">
                    {r[key].map((x) => (
                      <li key={x}>{x}</li>
                    ))}
                  </ul>
                </div>
              ) : null,
            )}
            <div className="grid gap-4 border-t border-zinc-100 pt-4 sm:grid-cols-2 dark:border-zinc-800">
              <div>
                <h3 className="mb-1.5 text-xs font-semibold tracking-wider text-zinc-400 uppercase">Search titles</h3>
                <div className="flex flex-wrap gap-1">{r.search_titles.map((t) => <Badge key={t}>{t}</Badge>)}</div>
              </div>
              <div>
                <h3 className="mb-1.5 text-xs font-semibold tracking-wider text-zinc-400 uppercase">Keywords</h3>
                <div className="flex flex-wrap gap-1">{r.keywords.map((t) => <Badge key={t}>{t}</Badge>)}</div>
              </div>
            </div>
            <div className="border-t border-zinc-100 pt-4 text-xs text-zinc-500 dark:border-zinc-800">
              <p className="mb-1.5 font-semibold tracking-wider text-zinc-400 uppercase">How it was drafted</p>
              <p>
                From {r.cards.length} memory card{r.cards.length === 1 ? "" : "s"}
                {r.cards.length > 0 && <>: {r.cards.map((c) => c.label).join(" · ")}</>}.
              </p>
              <p className="mt-1">
                {r.example_jobs.length
                  ? <>Example postings for current wording: {r.example_jobs.map((j) => j.label).join(" · ")}.</>
                  : "No fetched postings for this role yet; written from the model's knowledge of the market."}
              </p>
              <button type="button" onClick={() => setShowText((v) => !v)} className="mt-2 text-violet-700 hover:underline dark:text-violet-300">
                {showText ? "Hide" : "Show"} the exact text compared with jobs
              </button>
              {showText && <pre className="mt-2 max-h-80 overflow-auto rounded-md bg-zinc-50 p-3 font-mono text-[11px] whitespace-pre-wrap text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">{r.text}</pre>}
            </div>
          </div>
        ))}

      <Modal
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Replace your edits?"
        footer={
          <>
            <Button onClick={() => setConfirm(false)}>Cancel</Button>
            <Button variant="primary" onClick={() => void regenerate()}>
              Regenerate
            </Button>
          </>
        }
      >
        <p className="text-sm text-zinc-600 dark:text-zinc-400">You edited this context. Regenerating rewrites it from your current memory cards and your edits are lost.</p>
      </Modal>
    </Card>
  );
}

function TestPanel({ hasRoles }: { hasRoles: boolean }) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [result, setResult] = useState<RoleMatch[] | null>(null);
  const [running, setRunning] = useState(false);
  const run = async () => {
    setRunning(true);
    try {
      setResult(await api.testRoleContexts(text));
    } catch (e) {
      toast.error("Test failed", errorMessage(e));
    } finally {
      setRunning(false);
    }
  };
  return (
    <Card className="p-5">
      <div className="mb-1 flex items-center gap-2">
        <FlaskConical className="size-4 text-violet-600 dark:text-violet-400" />
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Test a job description</h2>
      </div>
      <p className="mb-3 text-xs text-zinc-500">Paste a posting to see how close it is to each role context (the same comparison scans use).</p>
      <Textarea rows={6} placeholder="Paste a job description…" value={text} onChange={(e) => setText(e.target.value)} />
      <div className="mt-3 flex justify-end">
        <Button size="sm" variant="primary" loading={running} disabled={!hasRoles || text.trim().length < 20} onClick={() => void run()}>
          Compare
        </Button>
      </div>
      {result && (
        <ol className="mt-4 space-y-2.5 border-t border-zinc-100 pt-4 dark:border-zinc-800">
          {result.length === 0 && <p className="text-sm text-zinc-500">No role contexts written yet.</p>}
          {result.map((m) => (
            <li key={m.role}>
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="truncate font-medium text-zinc-800 dark:text-zinc-200">{m.role}</span>
                <span className="shrink-0 text-zinc-500 tabular-nums">{pct(m.score)}</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
                <div className="h-full rounded-full bg-violet-600 dark:bg-violet-400" style={{ width: `${Math.max(2, Math.min(100, m.score * 100))}%` }} />
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

export default function RoleContexts() {
  const toast = useToast();
  const { data, setData, error, loading, reload } = useResource(api.listRoleContexts, {
    shouldPoll: (rows) => rows.some((r) => r.status === "pending" || (r.status === "missing" && r.in_roles)),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [ensuring, setEnsuring] = useState(false);

  const rows = data ?? [];
  const current = rows.filter((r) => r.in_roles);
  const removed = rows.filter((r) => !r.in_roles);
  const sel = rows.find((r) => r.role === selected) ?? current[0] ?? removed[0] ?? null;
  const needsWriting = current.some((r) => r.status === "missing" || r.status === "failed");

  const replace = (r: RoleContextOut) => setData((xs) => (xs ? xs.map((x) => (x.role === r.role ? r : x)) : xs));

  const ensure = async () => {
    setEnsuring(true);
    try {
      setData(await api.ensureRoleContexts());
    } catch (e) {
      toast.error("Couldn't start writing", errorMessage(e));
    } finally {
      setEnsuring(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Role contexts"
        subtitle="For each role you want, a job-description-style context written from your memory cards. Every fetched job is compared with the context of its role."
        actions={
          needsWriting ? (
            <Button variant="primary" icon={<RefreshCw className="size-4" />} loading={ensuring} onClick={() => void ensure()}>
              Write missing
            </Button>
          ) : undefined
        }
      />
      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} onRetry={reload} />
        </div>
      )}
      {loading && !data && <Skeleton className="h-64" />}
      {data && rows.length === 0 && (
        <Card>
          <EmptyState
            icon={<Brain className="size-5" />}
            title="No roles yet"
            body="Add the roles you want in Search Settings; each gets its context written automatically."
            action={
              <Link to="/job-search/settings#criteria">
                <Button>Search Settings</Button>
              </Link>
            }
          />
        </Card>
      )}
      {data && rows.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
          <nav aria-label="Roles" className="space-y-4">
            <ul className="space-y-0.5">
              {current.map((r) => (
                <li key={r.role}>
                  <button
                    type="button"
                    onClick={() => setSelected(r.role)}
                    className={cx(
                      "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm",
                      sel?.role === r.role ? "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-50" : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100",
                    )}
                  >
                    <StatusDot r={r} />
                    <span className="min-w-0 flex-1 truncate">{r.role}</span>
                    {r.memory_changed && <span className="text-[10px] text-amber-600 dark:text-amber-400">changed</span>}
                  </button>
                </li>
              ))}
            </ul>
            {removed.length > 0 && (
              <div>
                <p className="px-3 text-[11px] font-semibold tracking-wider text-zinc-400 uppercase">Removed roles</p>
                <ul className="mt-1 space-y-0.5">
                  {removed.map((r) => (
                    <li key={r.role}>
                      <button type="button" onClick={() => setSelected(r.role)} className={cx("w-full truncate rounded-md px-3 py-1.5 text-left text-xs", sel?.role === r.role ? "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-50" : "text-zinc-400 hover:text-zinc-700")}>
                        {r.role}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </nav>
          <div className="min-w-0 space-y-6">
            {sel &&
              (sel.status === "missing" ? (
                <Card className="flex items-center gap-3 px-5 py-6 text-sm text-zinc-600 dark:text-zinc-400">
                  <Spinner className="size-4" /> “{sel.role}” has no context yet; it's being written (or click Write missing).
                </Card>
              ) : (
                <ContextView key={sel.role} r={sel} onSaved={replace} onRegenerated={replace} />
              ))}
            <TestPanel hasRoles={current.length > 0} />
          </div>
        </div>
      )}
    </div>
  );
}
