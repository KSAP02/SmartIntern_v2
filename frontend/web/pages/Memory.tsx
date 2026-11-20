// Memory ▾ Cards: what your intern knows about you, as editable cards (stored text). Since
// Phase 2.6 cards aren't embedded: each role's context (Memory ▾ Role contexts) is written
// from them, and they prove the skills a job asks for.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Brain, Pin, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import type { CardKind, CardOut } from "../lib/types";
import { cx, timeAgo, useResource } from "../lib/util";
import { Badge, Button, Card, EmptyState, ErrorBanner, IconButton, Input, Label, PageHeader, Skeleton, Textarea, Toggle } from "../components/ui";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";

const KIND_ORDER: CardKind[] = ["summary", "experience", "project", "education", "skills", "certification", "custom"];
const KIND_LABEL: Record<CardKind, string> = {
  summary: "Summary",
  experience: "Experience",
  project: "Projects",
  education: "Education",
  skills: "Skills",
  certification: "Certifications",
  custom: "Custom",
};

function MemoryCard({
  card,
  onPatch,
  onDelete,
}: {
  card: CardOut;
  onPatch: (p: { title?: string; text?: string; enabled?: boolean; pinned?: boolean }) => Promise<void>;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(card.title);
  const [text, setText] = useState(card.text);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!editing) {
      setTitle(card.title);
      setText(card.text);
    }
  }, [card.title, card.text, editing]);
  const commit = async () => {
    const t = title.trim();
    const x = text.trim();
    if (!t || !x || (t === card.title && x === card.text)) {
      setEditing(false);
      setTitle(card.title);
      setText(card.text);
      return;
    }
    setSaving(true);
    await onPatch({ title: t, text: x });
    setSaving(false);
    setEditing(false);
  };

  return (
    <div
      id={`card-${card.id}`}
      className={cx("group rounded-xl bg-white p-4 ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-zinc-800", !card.enabled && "opacity-55")}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {editing ? (
            <Input value={title} onChange={(e) => setTitle(e.target.value)} className="h-8 font-medium" />
          ) : (
            <button onClick={() => setEditing(true)} className="text-left text-sm font-semibold text-zinc-900 hover:text-violet-700 dark:text-zinc-100 dark:hover:text-violet-300">
              {card.title}
            </button>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {card.origin === "user" && <Badge tone="accent">custom</Badge>}
            {card.user_edited && <Badge>edited</Badge>}
            {card.pinned && <Badge tone="amber">pinned</Badge>}
            {!card.enabled && <Badge>excluded</Badge>}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <IconButton label={card.pinned ? "Unpin" : "Pin"} onClick={() => void onPatch({ pinned: !card.pinned })} className={card.pinned ? "text-amber-500" : ""}>
            <Pin className={cx("size-3.5", card.pinned && "fill-current")} />
          </IconButton>
          <Toggle checked={card.enabled} onChange={(v) => void onPatch({ enabled: v })} label={card.enabled ? "Used for role contexts and skill proof (click to exclude)" : "Excluded (click to include)"} />
          <IconButton label="Delete card" onClick={onDelete} className="hover:text-rose-600">
            <Trash2 className="size-3.5" />
          </IconButton>
        </div>
      </div>
      {editing ? (
        <div className="mt-3">
          <Textarea
            autoFocus
            rows={Math.min(14, Math.max(4, text.split("\n").length + 1))}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void commit();
              if (e.key === "Escape") {
                setEditing(false);
                setTitle(card.title);
                setText(card.text);
              }
            }}
          />
          <div className="mt-2 flex items-center justify-between">
            <span className="text-[11px] text-zinc-400">Ctrl/⌘ + Enter to save · Esc to cancel</span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setEditing(false);
                  setTitle(card.title);
                  setText(card.text);
                }}
              >
                Cancel
              </Button>
              <Button size="sm" variant="primary" loading={saving} onClick={() => void commit()}>
                Save
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <p
          onClick={() => setEditing(true)}
          title="Click to edit"
          className="mt-2 cursor-text text-sm leading-relaxed whitespace-pre-wrap text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200"
        >
          {card.text}
        </p>
      )}
    </div>
  );
}

export default function Memory() {
  const toast = useToast();
  const { data, setData, error, loading, reload } = useResource(api.getMemory);
  const [rebuilding, setRebuilding] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newText, setNewText] = useState("");
  const [toDelete, setToDelete] = useState<CardOut | null>(null);

  const replaceCard = (c: CardOut) => setData((m) => (m ? { ...m, cards: m.cards.map((x) => (x.id === c.id ? c : x)) } : m));

  const patch = async (card: CardOut, p: { title?: string; text?: string; enabled?: boolean; pinned?: boolean }) => {
    try {
      const c = await api.patchCard(card.id, p);
      replaceCard(c);
      if (p.text !== undefined || p.title !== undefined) void reload();
    } catch (e) {
      toast.error("Couldn't update card", errorMessage(e));
    }
  };

  const rebuild = async () => {
    setRebuilding(true);
    try {
      const m = await api.rebuildMemory();
      setData(m);
      toast.success("Memory rebuilt", "Your custom and edited cards were kept.");
    } catch (e) {
      toast.error("Couldn't rebuild", errorMessage(e));
    } finally {
      setRebuilding(false);
    }
  };

  const add = async () => {
    try {
      await api.addCard({ title: newTitle.trim(), text: newText.trim() });
      setNewTitle("");
      setNewText("");
      setAdding(false);
      toast.success("Card added", "Role contexts show “memory changed” so you can regenerate them.");
      await reload();
    } catch (e) {
      toast.error("Couldn't add card", errorMessage(e));
    }
  };

  const remove = async (c: CardOut) => {
    setToDelete(null);
    try {
      await api.deleteCard(c.id);
      setData((m) => (m ? { ...m, cards: m.cards.filter((x) => x.id !== c.id) } : m));
    } catch (e) {
      toast.error("Couldn't delete card", errorMessage(e));
    }
  };

  const cards = data?.cards ?? [];
  const groups = KIND_ORDER.map((k) => ({
    kind: k,
    cards: cards.filter((c) => c.kind === k).sort((a, b) => Number(b.pinned) - Number(a.pinned) || a.position - b.position),
  })).filter((g) => g.cards.length > 0);

  return (
    <div>
      <PageHeader
        title="Memory cards"
        subtitle={
          data?.built_at
            ? `${cards.length} cards · built ${timeAgo(data.built_at)} · each role's context is written from these`
            : "What your intern knows about you. Each role's context (Role contexts) is written from these cards."
        }
        actions={
          <>
            <Link to="/memory/roles">
              <Button icon={<ArrowRight className="size-4" />}>Role contexts</Button>
            </Link>
            <Button icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>
              Add card
            </Button>
            <Button variant="primary" icon={<RefreshCw className="size-4" />} loading={rebuilding} onClick={() => void rebuild()}>
              Rebuild from profile
            </Button>
          </>
        }
      />

      {data?.memory_stale && (
        <div className="mb-6 flex items-center justify-between gap-3 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-200 dark:ring-amber-500/20">
          <span>Your profile changed since these cards were built.</span>
          <Button size="sm" loading={rebuilding} onClick={() => void rebuild()}>
            Rebuild now
          </Button>
        </div>
      )}
      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} onRetry={reload} />
        </div>
      )}

      <div>
        <div className="min-w-0">
          {loading && !data && (
            <div className="space-y-3">
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
            </div>
          )}
          {data && cards.length === 0 && (
            <Card>
              <EmptyState
                icon={<Brain className="size-5" />}
                title="No memory cards yet"
                body="Cards are built from your profile: one per role, project, degree and skill group. Fill in your profile first, then build."
                action={
                  <div className="flex gap-2">
                    <Link to="/profile">
                      <Button>Go to Me</Button>
                    </Link>
                    <Button variant="primary" loading={rebuilding} onClick={() => void rebuild()}>
                      Build from profile
                    </Button>
                  </div>
                }
              />
            </Card>
          )}
          <div className="space-y-8">
            {groups.map((g) => (
              <section key={g.kind}>
                <h2 className="mb-3 flex items-center gap-2 text-xs font-semibold tracking-wider text-zinc-400 uppercase">
                  {KIND_LABEL[g.kind]} <span className="rounded-full bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:bg-zinc-800">{g.cards.length}</span>
                </h2>
                <div className="space-y-3">
                  {g.cards.map((c) => (
                    <MemoryCard
                      key={c.id}
                      card={c}
                      onPatch={(p) => patch(c, p)}
                      onDelete={() => setToDelete(c)}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      </div>

      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title="Add a custom card"
        subtitle="Anything your resume doesn't say well: a side project, an achievement, what you're looking for."
        footer={
          <>
            <Button onClick={() => setAdding(false)}>Cancel</Button>
            <Button variant="primary" disabled={!newTitle.trim() || !newText.trim()} onClick={() => void add()}>
              Add card
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <Label>Title</Label>
            <Input autoFocus value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="e.g. Hackathon win" />
          </div>
          <div>
            <Label>Text</Label>
            <Textarea rows={6} value={newText} onChange={(e) => setNewText(e.target.value)} placeholder="Describe it the way you'd want a recruiter to read it." />
          </div>
        </div>
      </Modal>

      <Modal
        open={toDelete !== null}
        onClose={() => setToDelete(null)}
        title="Delete this card?"
        footer={
          <>
            <Button onClick={() => setToDelete(null)}>Cancel</Button>
            <Button variant="primary" className="bg-rose-600 hover:bg-rose-500" onClick={() => toDelete && void remove(toDelete)}>
              Delete
            </Button>
          </>
        }
      >
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {toDelete?.origin === "generated"
            ? "Generated cards come back if you rebuild from your profile. To keep it out of role contexts instead, switch it off."
            : "This custom card is removed for good."}
        </p>
      </Modal>
    </div>
  );
}
