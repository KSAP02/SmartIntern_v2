import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Brain,
  BriefcaseBusiness,
  CheckCircle2,
  FolderGit2,
  GraduationCap,
  Plus,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-react";
import { api, errorMessage } from "../lib/api";
import type {
  CertificationItem,
  EducationItem,
  FillChange,
  FillMode,
  FillPreview,
  ProfileOut,
  Profile,
  ProjectItem,
  RemotePreference,
  ResumeOut,
  SkillGroup,
  WorkItem,
} from "../lib/types";
import { cx, formatDate, newId, timeAgo } from "../lib/util";
import { Badge, Button, Card, ErrorBanner, IconButton, Input, Label, PageHeader, Segmented, Skeleton, Spinner, Textarea } from "../components/ui";
import { ChipInput } from "../components/ChipInput";
import { SkillGroupsEditor } from "../components/SkillGroupsEditor";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";

// ── helpers ───────────────────────────────────────────────────────────────────

type Origins = Record<string, string>;
const clone = <T,>(v: T): T => structuredClone(v);
const nn = (s: string): string | null => (s.trim() === "" ? null : s);

function OriginBadge({ origin, labels }: { origin: string | undefined; labels: Record<string, string> }) {
  if (!origin) return null;
  if (origin === "user") return <Badge tone="neutral">edited</Badge>;
  if (origin.startsWith("resume:")) {
    const id = origin.slice(7);
    return (
      <Badge tone="accent" title="Filled from this resume">
        from {labels[id] ?? "a deleted resume"}
      </Badge>
    );
  }
  return null;
}

function SectionCard({
  id,
  icon,
  title,
  hint,
  actions,
  children,
}: {
  id?: string;
  icon: ReactNode;
  title: string;
  hint?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card id={id} className="scroll-mt-24 p-6">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex size-8 items-center justify-center rounded-lg bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">{icon}</div>
          <div>
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{title}</h2>
            {hint && <p className="text-xs text-zinc-500 dark:text-zinc-400">{hint}</p>}
          </div>
        </div>
        {actions}
      </div>
      {children}
    </Card>
  );
}

function TextField({
  label,
  value,
  onChange,
  origin,
  labels,
  placeholder,
  type = "text",
  className,
}: {
  label: string;
  value: string | number | null;
  onChange: (v: string) => void;
  origin?: string;
  labels: Record<string, string>;
  placeholder?: string;
  type?: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <Label extra={<OriginBadge origin={origin} labels={labels} />}>{label}</Label>
      <Input type={type} value={value ?? ""} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) {
    if (!v.length) return "—";
    // Lists of objects (e.g. skill groups) are separated more strongly than plain strings.
    return v.every((x) => typeof x === "string") ? v.join(", ") : v.map(formatValue).join("  ·  ");
  }
  if (typeof v === "object" && v !== null && "items" in v && "name" in v) {
    const g = v as { name: string | null; items: string[] };
    return `${g.name ?? "Skills"}: ${g.items.join(", ")}`;
  }
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    const parts = Object.entries(o)
      .filter(([k, x]) => k !== "id" && x !== null && x !== "" && !(Array.isArray(x) && x.length === 0) && x !== false)
      .map(([k, x]) => (k === "bullets" && Array.isArray(x) ? `${x.length} bullet${x.length === 1 ? "" : "s"}` : formatValue(x)));
    return parts.join(" · ") || "—";
  }
  return String(v);
}

/**
 * Whether skills look unsorted, so "Group by theme" is worth offering: the old flat
 * lists ("Skills" / "Tools & technologies"), an "Other" or unnamed group, one big
 * catch-all group, or near-duplicate group names (e.g. after filling from two resumes).
 */
function needsGrouping(groups: SkillGroup[]): boolean {
  const filled = groups.filter((g) => g.items.length);
  if (filled.length === 0) return false;
  const key = (n: string | null) =>
    (n ?? "")
      .toLowerCase()
      .replace(/\band\b|&/g, " ")
      .replace(/[^a-z0-9]+/g, "");
  const generic = new Set(["", "skills", "toolstechnologies", "toolsframeworks", "tools", "other"]);
  if (filled.some((g) => generic.has(key(g.name)))) return true;
  if (filled.length === 1 && filled[0].items.length > 12) return true;
  const keys = filled.map((g) => key(g.name));
  return keys.some((a, i) => keys.some((b, j) => i !== j && (a === b || a.startsWith(b) || b.startsWith(a))));
}

const SECTION_TITLES: Record<string, string> = {
  personal: "Personal",
  headline: "Headline",
  skills: "Skills",
  work_history: "Work history",
  education: "Education",
  projects: "Projects",
  certifications: "Certifications",
};

// ── Fill in using resume ──────────────────────────────────────────────────────

function FillModal({
  open,
  onClose,
  onApplied,
}: {
  open: boolean;
  onClose: () => void;
  onApplied: (me: ProfileOut, applied: number) => void;
}) {
  const toast = useToast();
  const [resumes, setResumes] = useState<ResumeOut[] | null>(null);
  const [resumeId, setResumeId] = useState<number | null>(null);
  const [mode, setMode] = useState<FillMode>("empty_only");
  const [preview, setPreview] = useState<FillPreview | null>(null);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setPreview(null);
    setErr(null);
    api.listResumes().then(
      (rs) => {
        setResumes(rs);
        const parsed = rs.filter((r) => r.parse_status === "parsed");
        const def = parsed.find((r) => r.is_default) ?? parsed[0];
        setResumeId(def ? def.id : null);
      },
      (e) => setErr(errorMessage(e)),
    );
  }, [open]);

  useEffect(() => {
    if (!open || resumeId === null) return;
    let alive = true;
    setLoading(true);
    setErr(null);
    api
      .previewFill({ resume_id: resumeId, mode, exclude_fields: [] })
      .then(
        (p) => {
          if (!alive) return;
          setPreview(p);
          setExcluded(new Set(p.changes.filter((c) => c.user_edited).map((c) => c.path)));
        },
        (e) => alive && setErr(errorMessage(e)),
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [open, resumeId, mode]);

  const grouped = useMemo(() => {
    const g = new Map<string, FillChange[]>();
    for (const c of preview?.changes ?? []) {
      const list = g.get(c.section) ?? [];
      list.push(c);
      g.set(c.section, list);
    }
    return Array.from(g.entries());
  }, [preview]);

  const selected = (preview?.changes.length ?? 0) - Array.from(excluded).filter((p) => preview?.changes.some((c) => c.path === p)).length;

  const toggle = (path: string) =>
    setExcluded((s) => {
      const n = new Set(s);
      if (n.has(path)) n.delete(path);
      else n.add(path);
      return n;
    });

  const apply = async () => {
    if (resumeId === null) return;
    setApplying(true);
    try {
      const res = await api.applyFill({ resume_id: resumeId, mode, exclude_fields: Array.from(excluded) });
      onApplied(res.view, res.applied);
      onClose();
    } catch (e) {
      toast.error("Couldn't fill your profile", errorMessage(e));
    } finally {
      setApplying(false);
    }
  };

  const parsed = (resumes ?? []).filter((r) => r.parse_status === "parsed");

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title="Fill in using resume"
      subtitle="Pick a resume, review what changes, then apply. Nothing is saved until you click Apply."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={applying} disabled={!preview || selected === 0 || loading} onClick={apply} icon={<Wand2 className="size-4" />}>
            Apply {selected > 0 ? `${selected} change${selected === 1 ? "" : "s"}` : ""}
          </Button>
        </>
      }
    >
      {resumes === null && !err && <Skeleton className="h-24" />}
      {resumes !== null && parsed.length === 0 && (
        <div className="rounded-xl bg-zinc-50 p-5 text-sm text-zinc-600 dark:bg-zinc-950 dark:text-zinc-400">
          No parsed resumes yet.{" "}
          <Link to="/vault" className="font-medium text-violet-600 hover:underline dark:text-violet-400" onClick={onClose}>
            Upload one in the Vault
          </Link>{" "}
          and come back once it shows <Badge tone="green">Parsed</Badge>.
        </div>
      )}
      {parsed.length > 0 && (
        <div className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label>Resume</Label>
              <select
                value={resumeId ?? ""}
                onChange={(e) => setResumeId(Number(e.target.value))}
                className="h-10 w-full rounded-lg bg-white px-3 text-sm ring-1 ring-zinc-200 focus:ring-2 focus:ring-violet-500/60 focus:outline-none dark:bg-zinc-950 dark:ring-zinc-800"
              >
                {parsed.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.is_default ? "★ " : ""}
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label>Mode</Label>
              <Segmented
                value={mode}
                onChange={setMode}
                options={[
                  { value: "empty_only", label: "Fill empty fields only" },
                  { value: "replace", label: "Replace everything" },
                ]}
              />
            </div>
          </div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            {mode === "empty_only"
              ? "Only blank fields are filled. Anything you've already entered stays as it is."
              : "Values from the resume replace current ones. Fields you edited by hand start unchecked. Entries you added yourself are never deleted."}
          </p>

          {err && <ErrorBanner message={err} />}
          {loading && (
            <div className="flex items-center gap-2 py-6 text-sm text-zinc-500">
              <Spinner /> Comparing with your profile…
            </div>
          )}
          {!loading && preview && preview.changes.length === 0 && (
            <div className="flex items-center gap-2 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
              <CheckCircle2 className="size-4" /> Nothing to change. Your profile already has everything from this resume
              {mode === "empty_only" ? " (try Replace everything to overwrite)." : "."}
            </div>
          )}
          {!loading && preview && preview.changes.length > 0 && (
            <div className="space-y-4">
              <div className="flex items-center justify-between text-xs text-zinc-500">
                <span>
                  {preview.changes.length} change{preview.changes.length === 1 ? "" : "s"} found
                </span>
                <div className="flex gap-3">
                  <button className="hover:text-zinc-800 dark:hover:text-zinc-200" onClick={() => setExcluded(new Set())}>
                    Select all
                  </button>
                  <button
                    className="hover:text-zinc-800 dark:hover:text-zinc-200"
                    onClick={() => setExcluded(new Set(preview.changes.map((c) => c.path)))}
                  >
                    Select none
                  </button>
                </div>
              </div>
              {grouped.map(([section, changes]) => (
                <div key={section}>
                  <h4 className="mb-2 text-[11px] font-semibold tracking-wider text-zinc-400 uppercase">{SECTION_TITLES[section] ?? section}</h4>
                  <div className="divide-y divide-zinc-100 rounded-xl ring-1 ring-zinc-200 dark:divide-zinc-800 dark:ring-zinc-800">
                    {changes.map((c) => (
                      <label key={c.path} className="flex cursor-pointer items-start gap-3 px-4 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
                        <input
                          type="checkbox"
                          checked={!excluded.has(c.path)}
                          onChange={() => toggle(c.path)}
                          className="mt-0.5 size-4 accent-violet-600"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{c.label}</span>
                            <Badge tone={c.action === "add" ? "green" : c.action === "update" ? "blue" : "neutral"}>
                              {c.action === "add" ? "new" : c.action === "update" ? "update" : "set"}
                            </Badge>
                            {c.user_edited && (
                              <Badge tone="amber">
                                <AlertTriangle className="size-3" /> you edited this
                              </Badge>
                            )}
                          </div>
                          <div className="mt-1 grid gap-1 text-xs sm:grid-cols-[1fr_auto_1fr] sm:items-start">
                            <span className="break-words text-zinc-400 line-through decoration-zinc-300 dark:decoration-zinc-600">
                              {c.action === "add" ? "—" : formatValue(c.current)}
                            </span>
                            <span className="hidden text-zinc-300 sm:block">→</span>
                            <span className="break-words text-zinc-700 dark:text-zinc-300">{formatValue(c.incoming)}</span>
                          </div>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

// ── List section editors ──────────────────────────────────────────────────────

function ListControls({
  index,
  count,
  onMove,
  onRemove,
}: {
  index: number;
  count: number;
  onMove: (to: number) => void;
  onRemove: () => void;
}) {
  return (
    <div className="flex items-center gap-0.5">
      <IconButton label="Move up" disabled={index === 0} onClick={() => onMove(index - 1)}>
        <ArrowUp className="size-3.5" />
      </IconButton>
      <IconButton label="Move down" disabled={index === count - 1} onClick={() => onMove(index + 1)}>
        <ArrowDown className="size-3.5" />
      </IconButton>
      <IconButton label="Remove" onClick={onRemove} className="hover:text-rose-600">
        <Trash2 className="size-3.5" />
      </IconButton>
    </div>
  );
}

function move<T>(arr: T[], from: number, to: number): T[] {
  const a = arr.slice();
  const [x] = a.splice(from, 1);
  a.splice(to, 0, x);
  return a;
}

function ItemShell({ title, badge, controls, children }: { title: string; badge: ReactNode; controls: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-xl bg-zinc-50/70 p-4 ring-1 ring-zinc-200/70 dark:bg-zinc-950/50 dark:ring-zinc-800">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium text-zinc-800 dark:text-zinc-200">{title}</span>
          {badge}
        </div>
        {controls}
      </div>
      {children}
    </div>
  );
}

function BulletsEditor({ bullets, onChange }: { bullets: string[]; onChange: (b: string[]) => void }) {
  return (
    <div>
      <Label>Highlights</Label>
      <div className="space-y-2">
        {bullets.map((b, i) => (
          <div key={i} className="flex items-start gap-2">
            <span className="mt-3 size-1.5 shrink-0 rounded-full bg-zinc-300 dark:bg-zinc-600" />
            <Textarea
              rows={Math.min(4, Math.max(1, Math.ceil(b.length / 90)))}
              value={b}
              onChange={(e) => onChange(bullets.map((x, j) => (j === i ? e.target.value : x)))}
              className="min-h-10"
            />
            <IconButton label="Remove bullet" onClick={() => onChange(bullets.filter((_, j) => j !== i))} className="mt-1 hover:text-rose-600">
              <Trash2 className="size-3.5" />
            </IconButton>
          </div>
        ))}
        <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={() => onChange([...bullets, ""])}>
          Add highlight
        </Button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const EMPLOYMENT_TYPES = ["internship", "full_time", "part_time", "contract", "freelance"];

export default function ProfilePage() {
  const toast = useToast();
  const [me, setMe] = useState<ProfileOut | null>(null);
  const [draft, setDraft] = useState<Profile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [fillOpen, setFillOpen] = useState(false);
  const [grouping, setGrouping] = useState(false);

  const load = useCallback(async () => {
    try {
      const m = await api.getProfile();
      setMe(m);
      setDraft(clone(m.profile));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const dirty = useMemo(() => !!me && !!draft && JSON.stringify(me.profile) !== JSON.stringify(draft), [me, draft]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const update = (fn: (p: Profile) => void) =>
    setDraft((d) => {
      if (!d) return d;
      const n = clone(d);
      fn(n);
      return n;
    });

  // "Group by theme": the proposal lands in the unsaved draft, so it can be adjusted, then saved.
  const regroup = async () => {
    if (!draft) return;
    setGrouping(true);
    try {
      const { groups } = await api.regroupSkills(draft.skills.groups);
      update((d) => void (d.skills.groups = groups));
      toast.success(`Sorted into ${groups.length} group${groups.length === 1 ? "" : "s"}`, "Review the groups, then Save.");
    } catch (e) {
      toast.error("Couldn't group skills", errorMessage(e));
    } finally {
      setGrouping(false);
    }
  };

  const save = async (): Promise<boolean> => {
    if (!draft) return false;
    setSaving(true);
    try {
      const m = await api.putProfile(draft);
      setMe(m);
      setDraft(clone(m.profile));
      toast.success("Profile saved");
      return true;
    } catch (e) {
      toast.error("Couldn't save", errorMessage(e));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const openFill = async () => {
    if (dirty && !(await save())) return;
    setFillOpen(true);
  };

  const confirm = async () => {
    if (dirty && !(await save())) return;
    setConfirming(true);
    try {
      const m = await api.confirmProfile();
      setMe(m);
      toast.success("Profile confirmed", "Your intern will rely on these details.");
    } catch (e) {
      toast.error("Couldn't confirm", errorMessage(e));
    } finally {
      setConfirming(false);
    }
  };

  if (!me || !draft) {
    return error ? (
      <ErrorBanner message={error} onRetry={load} />
    ) : (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-64" />
        <Skeleton className="h-48" />
      </div>
    );
  }

  const o: Origins = me.field_origins;
  const L = me.resume_labels;
  const p = draft;
  const item = (section: string, id: string) => <OriginBadge origin={o[`${section}[${id}]`]} labels={L} />;
  const empty = !p.personal.full_name && p.work_history.length === 0 && p.education.length === 0;

  return (
    <div className="pb-24">
      <PageHeader
        title={p.personal.full_name || "Your profile"}
        subtitle={
          <>
            {me.completeness}% complete
            {me.confirmed_at ? ` · confirmed ${formatDate(me.confirmed_at)}` : " · not confirmed yet"}
            {me.updated_at ? ` · saved ${timeAgo(me.updated_at)}` : ""}
          </>
        }
        actions={
          <>
            <Button icon={<ShieldCheck className="size-4" />} loading={confirming} onClick={confirm}>
              {me.confirmed_at ? "Re-confirm" : "Confirm profile"}
            </Button>
            <Button variant="primary" icon={<Sparkles className="size-4" />} onClick={openFill} loading={saving && fillOpen}>
              Fill in using resume
            </Button>
          </>
        }
      />

      <div className="mb-6 h-1.5 overflow-hidden rounded-full bg-zinc-200/70 dark:bg-zinc-800">
        <div className="h-full rounded-full bg-violet-600 transition-[width] duration-700 dark:bg-violet-400" style={{ width: `${me.completeness}%` }} />
      </div>

      {me.memory_stale && (
        <div className="mb-6 flex items-center justify-between gap-3 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-200 dark:ring-amber-500/20">
          <span className="flex items-center gap-2">
            <Brain className="size-4" /> Your profile changed since your memory cards were built.
          </span>
          <Link to="/memory">
            <Button size="sm">Open Memory</Button>
          </Link>
        </div>
      )}

      {empty && (
        <Card className="mb-8 flex flex-col items-start gap-4 p-6 sm:flex-row sm:items-center">
          <div className="flex size-11 items-center justify-center rounded-xl bg-violet-600 text-white">
            <Sparkles className="size-5" />
          </div>
          <div className="flex-1">
            <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Start from a resume</p>
            <p className="text-sm text-zinc-500 dark:text-zinc-400">Fill in everything below in one click, then tweak whatever you like.</p>
          </div>
          <Button variant="primary" onClick={openFill}>
            Fill in using resume
          </Button>
        </Card>
      )}

      <div className="space-y-6">
        <SectionCard icon={<ShieldCheck className="size-4" />} title="Personal" hint="Used to fill in application forms exactly.">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField label="Full name" value={p.personal.full_name} origin={o["personal.full_name"]} labels={L} onChange={(v) => update((d) => void (d.personal.full_name = nn(v)))} className="sm:col-span-2" />
            <TextField label="Email" type="email" value={p.personal.email} origin={o["personal.email"]} labels={L} onChange={(v) => update((d) => void (d.personal.email = nn(v)))} />
            <TextField label="Phone" type="tel" value={p.personal.phone} origin={o["personal.phone"]} labels={L} onChange={(v) => update((d) => void (d.personal.phone = nn(v)))} />
          </div>
          <h3 className="mt-6 mb-3 text-xs font-semibold text-zinc-500">Address</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            {(["line1", "line2", "city", "state", "postal_code", "country"] as const).map((k) => (
              <TextField
                key={k}
                label={{ line1: "Address line 1", line2: "Address line 2", city: "City", state: "State / region", postal_code: "Postal code", country: "Country" }[k]}
                value={p.personal.address[k]}
                origin={o[`personal.address.${k}`]}
                labels={L}
                onChange={(v) => update((d) => void (d.personal.address[k] = nn(v)))}
              />
            ))}
          </div>
          <h3 className="mt-6 mb-3 text-xs font-semibold text-zinc-500">Links</h3>
          <div className="grid gap-4 sm:grid-cols-3">
            {(["linkedin", "github", "portfolio"] as const).map((k) => (
              <TextField
                key={k}
                label={{ linkedin: "LinkedIn", github: "GitHub", portfolio: "Portfolio" }[k]}
                value={p.personal.links[k]}
                origin={o[`personal.links.${k}`]}
                labels={L}
                placeholder="https://"
                onChange={(v) => update((d) => void (d.personal.links[k] = nn(v)))}
              />
            ))}
          </div>
          <div className="mt-4">
            <Label extra={<OriginBadge origin={o["personal.links.other"]} labels={L} />}>Other links</Label>
            <ChipInput value={p.personal.links.other} onChange={(v) => update((d) => void (d.personal.links.other = v))} placeholder="Paste a link and press Enter" />
          </div>
        </SectionCard>

        <SectionCard icon={<Sparkles className="size-4" />} title="Headline" hint="How you'd introduce yourself in two lines.">
          <div className="grid gap-4 sm:grid-cols-[1fr_10rem]">
            <TextField label="Current title" value={p.headline.current_title} origin={o["headline.current_title"]} labels={L} onChange={(v) => update((d) => void (d.headline.current_title = nn(v)))} />
            <TextField
              label="Years of experience"
              type="number"
              value={p.headline.years_experience}
              origin={o["headline.years_experience"]}
              labels={L}
              onChange={(v) => update((d) => void (d.headline.years_experience = v === "" ? null : Number(v)))}
            />
          </div>
          <div className="mt-4">
            <Label extra={<OriginBadge origin={o["headline.summary"]} labels={L} />}>Summary</Label>
            <Textarea rows={4} value={p.headline.summary ?? ""} onChange={(e) => update((d) => void (d.headline.summary = nn(e.target.value)))} />
          </div>
        </SectionCard>

        <SectionCard
          icon={<Wand2 className="size-4" />}
          title="Skills"
          hint="Grouped by theme; each group becomes one memory card. Drag skills between groups, or click to select and move."
          actions={
            <div className="flex items-center gap-2">
              <OriginBadge origin={o["skills.groups"]} labels={L} />
              {(grouping || needsGrouping(p.skills.groups)) && (
                <Button
                  size="sm"
                  icon={<Sparkles className="size-3.5" />}
                  loading={grouping}
                  onClick={regroup}
                  title="Your skills look unsorted. Sort them into themed groups (you can adjust before saving)."
                >
                  Group by theme
                </Button>
              )}
            </div>
          }
        >
          <SkillGroupsEditor groups={p.skills.groups} onChange={(groups) => update((d) => void (d.skills.groups = groups))} />
          <div className="mt-6">
            <Label extra={<OriginBadge origin={o["skills.languages"]} labels={L} />}>Languages (spoken)</Label>
            <ChipInput value={p.skills.languages} onChange={(v) => update((d) => void (d.skills.languages = v))} />
          </div>
        </SectionCard>

        <SectionCard
          icon={<BriefcaseBusiness className="size-4" />}
          title="Work history"
          hint="Most recent first. Each entry becomes a memory card."
          actions={
            <Button
              size="sm"
              icon={<Plus className="size-3.5" />}
              onClick={() =>
                update((d) =>
                  void d.work_history.unshift({ id: newId(), company: null, title: null, location: null, start: null, end: null, is_current: false, bullets: [] } as WorkItem),
                )
              }
            >
              Add role
            </Button>
          }
        >
          {p.work_history.length === 0 && <p className="text-sm text-zinc-500">No roles yet.</p>}
          <div className="space-y-3">
            {p.work_history.map((w, i) => {
              const set = (fn: (x: WorkItem) => void) => update((d) => fn(d.work_history[i]));
              return (
                <ItemShell
                  key={w.id}
                  title={[w.title, w.company].filter(Boolean).join(" at ") || "New role"}
                  badge={item("work_history", w.id)}
                  controls={
                    <ListControls
                      index={i}
                      count={p.work_history.length}
                      onMove={(to) => update((d) => void (d.work_history = move(d.work_history, i, to)))}
                      onRemove={() => update((d) => void d.work_history.splice(i, 1))}
                    />
                  }
                >
                  <div className="grid gap-3 sm:grid-cols-2">
                    <TextField label="Title" value={w.title} labels={L} onChange={(v) => set((x) => void (x.title = nn(v)))} />
                    <TextField label="Company" value={w.company} labels={L} onChange={(v) => set((x) => void (x.company = nn(v)))} />
                    <TextField label="Location" value={w.location} labels={L} onChange={(v) => set((x) => void (x.location = nn(v)))} />
                    <div className="grid grid-cols-2 gap-3">
                      <TextField label="Start" value={w.start} labels={L} placeholder="Jan 2024" onChange={(v) => set((x) => void (x.start = nn(v)))} />
                      <div>
                        <TextField label="End" value={w.is_current ? "" : w.end} labels={L} placeholder={w.is_current ? "Present" : "Jun 2024"} onChange={(v) => set((x) => void (x.end = nn(v)))} />
                      </div>
                    </div>
                  </div>
                  <label className="mt-3 flex w-fit cursor-pointer items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                    <input type="checkbox" checked={w.is_current} onChange={(e) => set((x) => void (x.is_current = e.target.checked))} className="size-4 accent-violet-600" />
                    I currently work here
                  </label>
                  <div className="mt-4">
                    <BulletsEditor bullets={w.bullets} onChange={(b) => set((x) => void (x.bullets = b))} />
                  </div>
                </ItemShell>
              );
            })}
          </div>
        </SectionCard>

        <SectionCard
          icon={<GraduationCap className="size-4" />}
          title="Education"
          actions={
            <Button
              size="sm"
              icon={<Plus className="size-3.5" />}
              onClick={() => update((d) => void d.education.push({ id: newId(), institution: null, degree: null, field: null, start: null, end: null, grade: null } as EducationItem))}
            >
              Add education
            </Button>
          }
        >
          {p.education.length === 0 && <p className="text-sm text-zinc-500">No education entries yet.</p>}
          <div className="space-y-3">
            {p.education.map((e, i) => {
              const set = (fn: (x: EducationItem) => void) => update((d) => fn(d.education[i]));
              return (
                <ItemShell
                  key={e.id}
                  title={[e.degree, e.institution].filter(Boolean).join(", ") || "New entry"}
                  badge={item("education", e.id)}
                  controls={
                    <ListControls
                      index={i}
                      count={p.education.length}
                      onMove={(to) => update((d) => void (d.education = move(d.education, i, to)))}
                      onRemove={() => update((d) => void d.education.splice(i, 1))}
                    />
                  }
                >
                  <div className="grid gap-3 sm:grid-cols-2">
                    <TextField label="Institution" value={e.institution} labels={L} onChange={(v) => set((x) => void (x.institution = nn(v)))} />
                    <TextField label="Degree" value={e.degree} labels={L} onChange={(v) => set((x) => void (x.degree = nn(v)))} />
                    <TextField label="Field of study" value={e.field} labels={L} onChange={(v) => set((x) => void (x.field = nn(v)))} />
                    <TextField label="Grade / GPA" value={e.grade} labels={L} onChange={(v) => set((x) => void (x.grade = nn(v)))} />
                    <TextField label="Start" value={e.start} labels={L} onChange={(v) => set((x) => void (x.start = nn(v)))} />
                    <TextField label="End" value={e.end} labels={L} onChange={(v) => set((x) => void (x.end = nn(v)))} />
                  </div>
                </ItemShell>
              );
            })}
          </div>
        </SectionCard>

        <SectionCard
          icon={<FolderGit2 className="size-4" />}
          title="Projects"
          actions={
            <Button
              size="sm"
              icon={<Plus className="size-3.5" />}
              onClick={() => update((d) => void d.projects.push({ id: newId(), name: null, description: null, tech: [], url: null } as ProjectItem))}
            >
              Add project
            </Button>
          }
        >
          {p.projects.length === 0 && <p className="text-sm text-zinc-500">No projects yet.</p>}
          <div className="space-y-3">
            {p.projects.map((pr, i) => {
              const set = (fn: (x: ProjectItem) => void) => update((d) => fn(d.projects[i]));
              return (
                <ItemShell
                  key={pr.id}
                  title={pr.name || "New project"}
                  badge={item("projects", pr.id)}
                  controls={
                    <ListControls
                      index={i}
                      count={p.projects.length}
                      onMove={(to) => update((d) => void (d.projects = move(d.projects, i, to)))}
                      onRemove={() => update((d) => void d.projects.splice(i, 1))}
                    />
                  }
                >
                  <div className="grid gap-3 sm:grid-cols-2">
                    <TextField label="Name" value={pr.name} labels={L} onChange={(v) => set((x) => void (x.name = nn(v)))} />
                    <TextField label="URL" value={pr.url} labels={L} placeholder="https://" onChange={(v) => set((x) => void (x.url = nn(v)))} />
                  </div>
                  <div className="mt-3">
                    <Label>Description</Label>
                    <Textarea rows={3} value={pr.description ?? ""} onChange={(e) => set((x) => void (x.description = nn(e.target.value)))} />
                  </div>
                  <div className="mt-3">
                    <Label>Tech</Label>
                    <ChipInput value={pr.tech} onChange={(v) => set((x) => void (x.tech = v))} />
                  </div>
                </ItemShell>
              );
            })}
          </div>
        </SectionCard>

        <SectionCard
          icon={<CheckCircle2 className="size-4" />}
          title="Certifications"
          actions={
            <Button
              size="sm"
              icon={<Plus className="size-3.5" />}
              onClick={() => update((d) => void d.certifications.push({ id: newId(), name: null, issuer: null, date: null } as CertificationItem))}
            >
              Add certification
            </Button>
          }
        >
          {p.certifications.length === 0 && <p className="text-sm text-zinc-500">No certifications yet.</p>}
          <div className="space-y-3">
            {p.certifications.map((c, i) => {
              const set = (fn: (x: CertificationItem) => void) => update((d) => fn(d.certifications[i]));
              return (
                <ItemShell
                  key={c.id}
                  title={c.name || "New certification"}
                  badge={item("certifications", c.id)}
                  controls={
                    <ListControls
                      index={i}
                      count={p.certifications.length}
                      onMove={(to) => update((d) => void (d.certifications = move(d.certifications, i, to)))}
                      onRemove={() => update((d) => void d.certifications.splice(i, 1))}
                    />
                  }
                >
                  <div className="grid gap-3 sm:grid-cols-3">
                    <TextField label="Name" value={c.name} labels={L} onChange={(v) => set((x) => void (x.name = nn(v)))} />
                    <TextField label="Issuer" value={c.issuer} labels={L} onChange={(v) => set((x) => void (x.issuer = nn(v)))} />
                    <TextField label="Date" value={c.date} labels={L} onChange={(v) => set((x) => void (x.date = nn(v)))} />
                  </div>
                </ItemShell>
              );
            })}
          </div>
        </SectionCard>

        <SectionCard
          icon={<ShieldCheck className="size-4" />}
          title="Preferences"
          hint="Only you set these. Resumes never change them. They decide which jobs your intern looks for."
        >
          <div className="space-y-4">
            <div>
              <Label extra={<OriginBadge origin={o["preferences.roles_of_interest"]} labels={L} />}>Roles you want</Label>
              <ChipInput value={p.preferences.roles_of_interest} onChange={(v) => update((d) => void (d.preferences.roles_of_interest = v))} placeholder="e.g. ML engineering intern" />
            </div>
            <div>
              <Label extra={<OriginBadge origin={o["preferences.preferred_locations"]} labels={L} />}>Preferred locations</Label>
              <ChipInput value={p.preferences.preferred_locations} onChange={(v) => update((d) => void (d.preferences.preferred_locations = v))} placeholder="e.g. Bengaluru, Remote" />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label>Work setup</Label>
                <Segmented<RemotePreference | "unset">
                  value={p.preferences.remote_preference ?? "unset"}
                  onChange={(v) => update((d) => void (d.preferences.remote_preference = v === "unset" ? null : v))}
                  options={[
                    { value: "unset", label: "—" },
                    { value: "any", label: "Any" },
                    { value: "remote", label: "Remote" },
                    { value: "hybrid", label: "Hybrid" },
                    { value: "onsite", label: "On-site" },
                  ]}
                />
              </div>
              <div>
                <Label>Employment types</Label>
                <div className="flex flex-wrap gap-1.5">
                  {EMPLOYMENT_TYPES.map((t) => {
                    const on = p.preferences.employment_types.includes(t);
                    return (
                      <button
                        key={t}
                        type="button"
                        onClick={() =>
                          update((d) => {
                            d.preferences.employment_types = on
                              ? d.preferences.employment_types.filter((x) => x !== t)
                              : [...d.preferences.employment_types, t];
                          })
                        }
                        className={cx(
                          "rounded-full px-3 py-1 text-xs font-medium ring-1 transition-colors duration-150",
                          on
                            ? "bg-violet-600 text-white ring-violet-600"
                            : "bg-white text-zinc-600 ring-zinc-200 hover:ring-violet-300 dark:bg-zinc-950 dark:text-zinc-400 dark:ring-zinc-800",
                        )}
                      >
                        {t.replace("_", " ")}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <TextField
                label="Minimum salary"
                type="number"
                value={p.preferences.minimum_salary}
                labels={L}
                onChange={(v) => update((d) => void (d.preferences.minimum_salary = v === "" ? null : Number(v)))}
              />
              <TextField label="Currency" value={p.preferences.salary_currency} labels={L} placeholder="INR" onChange={(v) => update((d) => void (d.preferences.salary_currency = nn(v)))} />
              <TextField label="Notice period" value={p.preferences.notice_period} labels={L} placeholder="Immediate" onChange={(v) => update((d) => void (d.preferences.notice_period = nn(v)))} />
              <TextField
                label="Work authorization"
                value={p.preferences.work_authorization}
                labels={L}
                placeholder="e.g. Indian citizen"
                className="sm:col-span-2"
                onChange={(v) => update((d) => void (d.preferences.work_authorization = nn(v)))}
              />
              <TextField
                label="Earliest start date"
                type="date"
                value={p.preferences.earliest_start_date}
                labels={L}
                onChange={(v) => update((d) => void (d.preferences.earliest_start_date = nn(v)))}
              />
            </div>
          </div>
        </SectionCard>
      </div>

      {dirty && (
        <div className="pop-in fixed inset-x-0 bottom-4 z-40 flex justify-center px-4 lg:pl-60">
          <div className="flex w-full max-w-xl items-center justify-between gap-3 rounded-lg bg-zinc-900 px-4 py-3 text-white shadow-lg dark:bg-zinc-100 dark:text-zinc-900">
            <span className="text-sm">You have unsaved changes</span>
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" className="text-zinc-300 hover:bg-zinc-800 hover:text-white dark:text-zinc-600 dark:hover:bg-zinc-200 dark:hover:text-zinc-900" onClick={() => setDraft(clone(me.profile))}>
                Discard
              </Button>
              <Button size="sm" variant="primary" loading={saving} onClick={() => void save()}>
                Save changes
              </Button>
            </div>
          </div>
        </div>
      )}

      <FillModal
        open={fillOpen}
        onClose={() => setFillOpen(false)}
        onApplied={(m, applied) => {
          setMe(m);
          setDraft(clone(m.profile));
          toast.success(`Filled ${applied} field${applied === 1 ? "" : "s"}`, "Review them below. Badges show where each value came from.");
        }}
      />
    </div>
  );
}
