import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, FileText, Pencil, RefreshCw, Star, Trash2, UserRound } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import type { Profile, ResumeDetail, ResumeOut } from "../lib/types";
import { cx, formatBytes, timeAgo, useResource } from "../lib/util";
import { Badge, Button, Card, EmptyState, ErrorBanner, IconButton, Input, PageHeader, Segmented, Skeleton, Spinner } from "../components/ui";
import { Dropzone } from "../components/Dropzone";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";

export function StatusChip({ r }: { r: ResumeOut }) {
  switch (r.parse_status) {
    case "pending":
      return (
        <Badge tone="neutral">
          <Spinner className="size-3" /> Queued
        </Badge>
      );
    case "parsing":
      return (
        <Badge tone="blue">
          <Spinner className="size-3 text-sky-500" /> Parsing
        </Badge>
      );
    case "parsed":
      return <Badge tone="green">Parsed</Badge>;
    case "failed":
      return (
        <Badge tone="red" title={r.parse_error ?? undefined}>
          Failed
        </Badge>
      );
  }
}

function LabelEditor({ r, onSave }: { r: ResumeOut; onSave: (label: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(r.label);
  useEffect(() => setValue(r.label), [r.label]);

  if (!editing) {
    return (
      <button
        onClick={(e) => {
          e.stopPropagation();
          setEditing(true);
        }}
        className="group/label flex min-w-0 items-center gap-1.5 text-left"
        title="Rename"
      >
        <span className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-50">{r.label}</span>
        <Pencil className="size-3 shrink-0 text-zinc-400 opacity-0 transition-opacity group-hover/label:opacity-100" />
      </button>
    );
  }
  const commit = async () => {
    setEditing(false);
    const v = value.trim();
    if (v && v !== r.label) await onSave(v);
    else setValue(r.label);
  };
  return (
    <Input
      autoFocus
      value={value}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") void commit();
        if (e.key === "Escape") {
          setValue(r.label);
          setEditing(false);
        }
      }}
      className="h-8"
    />
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h4 className="mb-2 text-[11px] font-semibold tracking-wider text-zinc-400 uppercase">{title}</h4>
      <div className="space-y-2 text-sm text-zinc-700 dark:text-zinc-300">{children}</div>
    </div>
  );
}

function ParsedSummary({ p }: { p: Profile }) {
  const addr = [p.personal.address.city, p.personal.address.state, p.personal.address.country].filter(Boolean).join(", ");
  const links = [p.personal.links.linkedin, p.personal.links.github, p.personal.links.portfolio, ...p.personal.links.other].filter(Boolean);
  const allSkills = p.skills.groups.flatMap((g) => g.items);
  return (
    <div className="space-y-6">
      <Section title="Personal">
        <p className="text-base font-semibold text-zinc-900 dark:text-zinc-50">{p.personal.full_name ?? "Name not found"}</p>
        <p className="text-zinc-500">{[p.personal.email, p.personal.phone, addr].filter(Boolean).join(" · ") || "No contact details found"}</p>
        {links.length > 0 && <p className="break-all text-xs text-zinc-500">{links.join(" · ")}</p>}
      </Section>
      {(p.headline.current_title || p.headline.summary) && (
        <Section title="Headline">
          {p.headline.current_title && <p className="font-medium">{p.headline.current_title}</p>}
          {p.headline.summary && <p className="text-zinc-500">{p.headline.summary}</p>}
        </Section>
      )}
      {p.work_history.length > 0 && (
        <Section title={`Experience (${p.work_history.length})`}>
          {p.work_history.map((w) => (
            <div key={w.id}>
              <p className="font-medium">
                {w.title ?? "Role"} {w.company && <span className="text-zinc-500">at {w.company}</span>}
              </p>
              <p className="text-xs text-zinc-500">{[w.start, w.is_current ? "Present" : w.end].filter(Boolean).join(" – ")}</p>
            </div>
          ))}
        </Section>
      )}
      {p.education.length > 0 && (
        <Section title="Education">
          {p.education.map((e) => (
            <p key={e.id}>
              <span className="font-medium">{[e.degree, e.field].filter(Boolean).join(", ") || "Degree"}</span>
              {e.institution && <span className="text-zinc-500"> · {e.institution}</span>}
            </p>
          ))}
        </Section>
      )}
      {p.projects.length > 0 && (
        <Section title={`Projects (${p.projects.length})`}>
          {p.projects.map((pr) => (
            <p key={pr.id} className="font-medium">
              {pr.name}
            </p>
          ))}
        </Section>
      )}
      {allSkills.length > 0 && (
        <Section title="Skills & tools">
          <div className="flex flex-wrap gap-1.5">
            {allSkills.map((s, i) => (
              <Badge key={`${s}-${i}`}>{s}</Badge>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

function ResumeDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const [detail, setDetail] = useState<ResumeDetail | null>(null);
  const [tab, setTab] = useState<"parsed" | "text">("parsed");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setErr(null);
    setTab("parsed");
    if (id === null) return;
    api.getResume(id).then(setDetail, (e) => setErr(errorMessage(e)));
  }, [id]);

  return (
    <Modal
      open={id !== null}
      onClose={onClose}
      side
      title={detail?.label ?? "Resume"}
      subtitle={detail ? `${detail.original_filename} · ${formatBytes(detail.size_bytes)} · uploaded ${timeAgo(detail.created_at)}` : undefined}
      footer={
        detail && (
          <>
            <a href={api.resumeFileUrl(detail.id)} target="_blank" rel="noreferrer">
              <Button icon={<ExternalLink className="size-4" />}>Open original</Button>
            </a>
            {detail.parse_status === "parsed" && (
              <Link to="/profile">
                <Button variant="primary" icon={<UserRound className="size-4" />}>
                  Use on My Profile
                </Button>
              </Link>
            )}
          </>
        )
      }
    >
      {err && <ErrorBanner message={err} />}
      {!detail && !err && (
        <div className="space-y-3">
          <Skeleton className="h-6 w-1/2" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-32" />
        </div>
      )}
      {detail && (
        <div className="space-y-5">
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { value: "parsed", label: "Parsed fields" },
              { value: "text", label: "Extracted text" },
            ]}
          />
          {tab === "parsed" &&
            (detail.parsed_data ? (
              <ParsedSummary p={detail.parsed_data} />
            ) : (
              <p className="text-sm text-zinc-500">
                {detail.parse_status === "failed"
                  ? `Parsing failed: ${detail.parse_error ?? "unknown error"}`
                  : "Not parsed yet. This updates automatically."}
              </p>
            ))}
          {tab === "text" && (
            <pre className="max-h-[60vh] overflow-auto rounded-xl bg-zinc-50 p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap text-zinc-700 ring-1 ring-zinc-200 dark:bg-zinc-950 dark:text-zinc-300 dark:ring-zinc-800">
              {detail.extracted_text || "No text extracted yet."}
            </pre>
          )}
        </div>
      )}
    </Modal>
  );
}

export default function Vault() {
  const toast = useToast();
  const { data, setData, error, loading, reload } = useResource(api.listResumes, {
    shouldPoll: (rs) => rs.some((r) => r.parse_status === "pending" || r.parse_status === "parsing"),
  });
  const [uploading, setUploading] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<ResumeOut | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  // Toast when a resume finishes parsing.
  const prev = useRef<Record<number, string>>({});
  useEffect(() => {
    if (!data) return;
    const next: Record<number, string> = {};
    for (const r of data) {
      next[r.id] = r.parse_status;
      const was = prev.current[r.id];
      if (was && was !== r.parse_status) {
        if (r.parse_status === "parsed") toast.success(`${r.label} is ready`, "Use it on My Profile to fill in your details.");
        if (r.parse_status === "failed") toast.error(`Couldn't parse ${r.label}`, r.parse_error ?? undefined);
      }
    }
    prev.current = next;
  }, [data, toast]);

  const upload = async (files: File[]) => {
    setUploading(true);
    try {
      const res = await api.uploadResumes(files);
      for (const e of res.errors) toast.error(`${e.filename} wasn't uploaded`, e.detail);
      const fresh = res.items.filter((i) => !res.duplicates.includes(i.id)).length;
      if (fresh) toast.info(`Uploaded ${fresh} resume${fresh > 1 ? "s" : ""}`, "Parsing in the background…");
      if (res.duplicates.length) toast.info("Already in your vault", "That file was uploaded before, so it wasn't added again.");
      await reload();
    } catch (e) {
      toast.error("Upload failed", errorMessage(e));
    } finally {
      setUploading(false);
    }
  };

  const patch = async (r: ResumeOut, p: { label?: string; is_default?: boolean }) => {
    try {
      await api.patchResume(r.id, p);
      await reload();
    } catch (e) {
      toast.error("Couldn't update resume", errorMessage(e));
    }
  };

  const reparse = async (r: ResumeOut) => {
    setBusyId(r.id);
    try {
      const updated = await api.reparseResume(r.id);
      setData((rs) => (rs ? rs.map((x) => (x.id === r.id ? updated : x)) : rs));
      toast.info(`Re-parsing ${r.label}`);
    } catch (e) {
      toast.error("Couldn't re-parse", errorMessage(e));
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (r: ResumeOut) => {
    setConfirmDelete(null);
    try {
      await api.deleteResume(r.id);
      toast.success(`Deleted ${r.label}`, "Profile values already filled from it are kept.");
      await reload();
    } catch (e) {
      toast.error("Couldn't delete", errorMessage(e));
    }
  };

  const resumes = data ?? [];

  return (
    <div>
      <PageHeader title="Vault" subtitle="Your resume library. Upload as many versions as you like; each one is parsed on its own." />

      <Dropzone onFiles={upload} busy={uploading} compact={resumes.length > 0} />

      <div className="mt-8">
        {error && <ErrorBanner message={error} onRetry={reload} />}
        {loading && !data && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
          </div>
        )}
        {data && resumes.length === 0 && (
          <Card>
            <EmptyState
              icon={<FileText className="size-5" />}
              title="No resumes yet"
              body="Drop a PDF or DOCX above. Your intern will read it and pull out your details so you can fill in your profile in one click."
            />
          </Card>
        )}
        {resumes.length > 0 && (
          <>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                {resumes.length} resume{resumes.length > 1 ? "s" : ""}
              </h2>
              <p className="text-xs text-zinc-500">★ marks your default resume</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {resumes.map((r) => (
                <Card
                  key={r.id}
                  onClick={() => setOpenId(r.id)}
                  className={cx(
                    "group cursor-pointer p-4 transition-colors duration-150 hover:border-zinc-400 dark:hover:border-zinc-600",
                    r.is_default && "ring-violet-300 dark:ring-violet-500/40",
                  )}
                >
                  <div className="flex items-start gap-3">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-zinc-100 text-[10px] font-bold text-zinc-500 uppercase dark:bg-zinc-800 dark:text-zinc-400">
                      {r.original_filename.split(".").pop()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <LabelEditor r={r} onSave={(label) => patch(r, { label })} />
                      </div>
                      <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
                        {r.original_filename} · {formatBytes(r.size_bytes)} · {timeAgo(r.created_at)}
                      </p>
                      <div className="mt-2.5 flex items-center gap-2">
                        <StatusChip r={r} />
                        {r.is_default && <Badge tone="accent">Default</Badge>}
                      </div>
                      {r.parse_status === "failed" && r.parse_error && (
                        <p className="mt-2 line-clamp-2 text-xs text-rose-600 dark:text-rose-400">{r.parse_error}</p>
                      )}
                    </div>
                    <div className="flex shrink-0 flex-col items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
                      <IconButton
                        label={r.is_default ? "Default resume" : "Make default"}
                        onClick={() => !r.is_default && patch(r, { is_default: true })}
                        className={r.is_default ? "text-amber-500 hover:text-amber-500" : ""}
                      >
                        <Star className={cx("size-4", r.is_default && "fill-current")} />
                      </IconButton>
                      <IconButton
                        label="Re-parse"
                        disabled={busyId === r.id || r.parse_status === "parsing" || r.parse_status === "pending"}
                        onClick={() => reparse(r)}
                      >
                        <RefreshCw className="size-4" />
                      </IconButton>
                      <IconButton label="Delete" onClick={() => setConfirmDelete(r)} className="hover:text-rose-600">
                        <Trash2 className="size-4" />
                      </IconButton>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </>
        )}
      </div>

      <ResumeDrawer id={openId} onClose={() => setOpenId(null)} />

      <Modal
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        title={`Delete ${confirmDelete?.label ?? "resume"}?`}
        footer={
          <>
            <Button onClick={() => setConfirmDelete(null)}>Cancel</Button>
            <Button variant="primary" className="bg-rose-600 hover:bg-rose-500" onClick={() => confirmDelete && remove(confirmDelete)}>
              Delete
            </Button>
          </>
        }
      >
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          The file and its parsed data are removed. Anything already filled into your profile from it stays.
        </p>
      </Modal>
    </div>
  );
}
