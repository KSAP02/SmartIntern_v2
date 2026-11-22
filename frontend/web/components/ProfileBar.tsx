// Phase 2.8: several profiles, one active. Switching changes the profile below, its memory cards,
// role contexts and roles; the shared jobs are re-scored in the background.
import { useCallback, useEffect, useRef, useState } from "react";
import { Copy, FileText, Plus, Settings2, Trash2 } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import type { ProfilesOut, ResumeOut } from "../lib/types";
import { cx } from "../lib/util";
import { Button, Card, Input, Label, Segmented, Spinner } from "./ui";
import { Modal } from "./Modal";
import { Select } from "./settings/form";
import { useToast } from "./Toast";

/** Fired after a switch, so the sidebar and open pages reload. */
export const PROFILE_EVENT = "smartintern:profile";

export function ProfileBar({ dirty, onSwitched }: { dirty: boolean; onSwitched: () => void }) {
  const toast = useToast();
  const [data, setData] = useState<ProfilesOut | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [managing, setManaging] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.listProfiles());
    } catch (e) {
      toast.error("Couldn't load profiles", errorMessage(e));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    void load();
  }, [load]);

  // While the switch follow-up runs (cards, role contexts, re-scoring jobs), poll its progress.
  const running = !!data?.switching.running;
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(t);
  }, [running, load]);
  // When it finishes, the page reloads (the profile's cards were built, jobs re-scored).
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) {
      onSwitched();
      window.dispatchEvent(new Event(PROFILE_EVENT));
    }
    wasRunning.current = running;
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps

  const activate = async (id: number) => {
    if (!data || id === data.active_id) return;
    if (dirty && !window.confirm("You have unsaved changes on this profile. Switch anyway and lose them?")) return;
    setBusy(id);
    try {
      setData(await api.activateProfile(id));
      onSwitched();
      window.dispatchEvent(new Event(PROFILE_EVENT));
    } catch (e) {
      toast.error("Couldn't switch profile", errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  if (!data) return null;
  const active = data.profiles.find((p) => p.active);

  return (
    <Card className="mb-6 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-xs text-zinc-500 dark:text-zinc-400">Profiles</span>
        {data.profiles.map((p) => (
          <button
            key={p.id}
            onClick={() => void activate(p.id)}
            disabled={busy !== null}
            title={p.active ? "Active profile" : `Switch to ${p.name}`}
            className={cx(
              "inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-sm transition-colors",
              p.active
                ? "bg-violet-600 text-white dark:bg-violet-500"
                : "text-zinc-700 ring-1 ring-zinc-200 hover:bg-zinc-100 dark:text-zinc-300 dark:ring-zinc-800 dark:hover:bg-zinc-900",
            )}
          >
            {busy === p.id && <Spinner className="size-3.5" />}
            {p.name}
          </button>
        ))}
        <div className="ml-auto flex gap-1">
          <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => setCreating(true)}>
            New profile
          </Button>
          <Button size="sm" variant="ghost" icon={<Settings2 className="size-3.5" />} onClick={() => setManaging(true)}>
            Manage
          </Button>
        </div>
      </div>
      <p className="mt-3 flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
        {running ? (
          <>
            <Spinner className="size-3.5" /> Switching to {active?.name}: {data.switching.step ?? "working"}… (jobs are re-scored for this profile; no job requests)
          </>
        ) : data.switching.error ? (
          <span className="text-rose-600 dark:text-rose-400">The last switch didn't finish: {data.switching.error}. Switch again to retry.</span>
        ) : active ? (
          <>
            {active.resume_label ? `Built on ${active.resume_label}` : "No resume chosen"} · {active.cards} memory card{active.cards === 1 ? "" : "s"} ·{" "}
            {active.roles.length ? `Roles: ${active.roles.join(", ")}` : "No roles yet (Search Settings)"}
          </>
        ) : null}
      </p>
      <NewProfileModal open={creating} onClose={() => setCreating(false)} data={data} onCreated={(d) => setData(d)} onSwitch={activate} />
      <ManageModal open={managing} onClose={() => setManaging(false)} data={data} onChanged={setData} />
    </Card>
  );
}

function useResumes(open: boolean) {
  const [resumes, setResumes] = useState<ResumeOut[]>([]);
  useEffect(() => {
    if (open) api.listResumes().then(setResumes, () => setResumes([]));
  }, [open]);
  return resumes;
}

function NewProfileModal({
  open,
  onClose,
  data,
  onCreated,
  onSwitch,
}: {
  open: boolean;
  onClose: () => void;
  data: ProfilesOut;
  onCreated: (d: ProfilesOut) => void;
  onSwitch: (id: number) => Promise<void>;
}) {
  const toast = useToast();
  const resumes = useResumes(open).filter((r) => r.parse_status === "parsed");
  const [mode, setMode] = useState<"resume" | "copy">("resume");
  const [resumeId, setResumeId] = useState<number | null>(null);
  const [copyOf, setCopyOf] = useState<number>(data.active_id);
  const [name, setName] = useState("");
  const [switchNow, setSwitchNow] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName("");
    setCopyOf(data.active_id);
  }, [open, data.active_id]);
  useEffect(() => {
    if (resumeId === null && resumes.length) setResumeId(resumes[0].id);
  }, [resumes, resumeId]);

  const create = async () => {
    setSaving(true);
    try {
      const before = new Set(data.profiles.map((p) => p.id));
      const out = await api.createProfile(
        mode === "resume" ? { name: name || null, resume_id: resumeId } : { name: name || null, copy_of: copyOf },
      );
      onCreated(out);
      const made = out.profiles.find((p) => !before.has(p.id));
      toast.success("Profile created", made ? made.name : undefined);
      onClose();
      if (switchNow && made) await onSwitch(made.id);
    } catch (e) {
      toast.error("Couldn't create the profile", errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const ready = mode === "copy" || resumeId !== null;
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New profile"
      subtitle="Each profile has its own details, memory cards, role contexts and roles. Jobs are shared."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={saving} disabled={!ready} onClick={() => void create()}>
            Create
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Segmented
          value={mode}
          onChange={setMode}
          options={[
            { value: "resume", label: "From a resume" },
            { value: "copy", label: "Copy a profile" },
          ]}
        />
        {mode === "resume" ? (
          <div>
            <Label>Resume</Label>
            {resumes.length ? (
              <Select className="w-full" value={resumeId ?? ""} onChange={(e) => setResumeId(Number(e.target.value))}>
                {resumes.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                  </option>
                ))}
              </Select>
            ) : (
              <p className="flex items-center gap-2 text-sm text-zinc-500">
                <FileText className="size-4" /> No parsed resume yet: upload one in the Vault.
              </p>
            )}
            <p className="mt-1.5 text-xs text-zinc-500">Every field is filled from it; edit anything afterwards.</p>
          </div>
        ) : (
          <div>
            <Label>Copy</Label>
            <Select className="w-full" value={copyOf} onChange={(e) => setCopyOf(Number(e.target.value))}>
              {data.profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </div>
        )}
        <div>
          <Label>Name (optional)</Label>
          <Input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder={mode === "resume" ? "The resume's name" : "“… (copy)”"} />
        </div>
        <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
          <input type="checkbox" checked={switchNow} onChange={(e) => setSwitchNow(e.target.checked)} />
          Switch to it now
        </label>
        <p className="text-xs text-zinc-500">
          It starts with the current profile's roles. The first switch to it builds its memory cards and writes a role context per role (one AI call
          each).
        </p>
      </div>
    </Modal>
  );
}

function ManageModal({ open, onClose, data, onChanged }: { open: boolean; onClose: () => void; data: ProfilesOut; onChanged: (d: ProfilesOut) => void }) {
  const toast = useToast();
  const resumes = useResumes(open);
  const [names, setNames] = useState<Record<number, string>>({});

  useEffect(() => {
    if (open) setNames(Object.fromEntries(data.profiles.map((p) => [p.id, p.name])));
  }, [open, data.profiles]);

  const patch = async (id: number, body: { name?: string; resume_id?: number }) => {
    try {
      onChanged(await api.renameProfile(id, body));
    } catch (e) {
      toast.error("Couldn't save", errorMessage(e));
    }
  };
  const remove = async (id: number, name: string) => {
    if (!window.confirm(`Delete the profile “${name}” with its memory cards and role contexts? Jobs are kept.`)) return;
    try {
      await api.deleteProfile(id);
      onChanged(await api.listProfiles());
      toast.success("Profile deleted");
    } catch (e) {
      toast.error("Couldn't delete", errorMessage(e));
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Manage profiles" footer={<Button onClick={onClose}>Done</Button>}>
      <div className="space-y-3">
        {data.profiles.map((p) => (
          <div key={p.id} className="grid items-center gap-2 sm:grid-cols-[1fr_12rem_auto]">
            <Input
              value={names[p.id] ?? p.name}
              maxLength={80}
              aria-label="Profile name"
              onChange={(e) => setNames((n) => ({ ...n, [p.id]: e.target.value }))}
              onBlur={() => {
                const v = (names[p.id] ?? "").trim();
                if (v && v !== p.name) void patch(p.id, { name: v });
              }}
            />
            <Select
              value={p.resume_id ?? ""}
              aria-label="Built on resume"
              onChange={(e) => e.target.value && void patch(p.id, { resume_id: Number(e.target.value) })}
            >
              <option value="">No resume</option>
              {resumes.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </Select>
            <Button
              size="sm"
              variant="danger"
              icon={<Trash2 className="size-3.5" />}
              disabled={p.active || data.profiles.length === 1}
              title={p.active ? "Switch to another profile first" : "Delete"}
              onClick={() => void remove(p.id, p.name)}
            >
              Delete
            </Button>
          </div>
        ))}
        <p className="flex items-center gap-1.5 text-xs text-zinc-500">
          <Copy className="size-3.5" /> “Built on” is the resume Fill in using resume starts from.
        </p>
      </div>
    </Modal>
  );
}
