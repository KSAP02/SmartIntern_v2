import { useState } from "react";
import type { DragEvent } from "react";
import { ArrowDown, ArrowUp, FolderPlus, Plus, Trash2, X } from "lucide-react";
import type { SkillGroup } from "../lib/types";
import { cx, newId } from "../lib/util";
import { Button, IconButton, Input } from "./ui";

const MIME = "text/x-skill";
const norm = (s: string) => s.trim().toLowerCase();

/** Remove `items` from every group, then insert them into `target` (a group id or "new") before `before`. */
function moveItems(groups: SkillGroup[], items: string[], target: string, before?: string): SkillGroup[] {
  const keys = new Set(items.map(norm));
  const next = groups.map((g) => ({ ...g, items: g.items.filter((s) => !keys.has(norm(s))) }));
  if (target === "new") return [...next, { id: newId(), name: null, items }];
  return next.map((g) => {
    if (g.id !== target) return g;
    const at = before ? g.items.findIndex((s) => norm(s) === norm(before)) : -1;
    const list = g.items.slice();
    list.splice(at < 0 ? list.length : at, 0, ...items);
    return { ...g, items: list };
  });
}

/**
 * Edit themed skill groups by hand: rename, reorder and delete groups; add, remove and
 * move skills. Move a skill by dragging it onto another group (or onto a skill to place it
 * there), or click skills to select them and use "Move to". A skill lives in one group only:
 * typing one that's already elsewhere moves it here.
 */
export function SkillGroupsEditor({ groups, onChange }: { groups: SkillGroup[]; onChange: (g: SkillGroup[]) => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [over, setOver] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const isSel = (s: string) => selected.some((x) => norm(x) === norm(s));
  const toggle = (s: string) => setSelected((cur) => (cur.some((x) => norm(x) === norm(s)) ? cur.filter((x) => norm(x) !== norm(s)) : [...cur, s]));
  const setGroup = (i: number, patch: Partial<SkillGroup>) => onChange(groups.map((g, j) => (j === i ? { ...g, ...patch } : g)));

  const move = (items: string[], target: string, before?: string) => {
    if (before && items.some((s) => norm(s) === norm(before))) return; // dropped onto itself
    onChange(moveItems(groups, items, target, before));
    setSelected([]);
  };

  const add = (g: SkillGroup, raw: string) => {
    const parts = raw.split(",").map((s) => s.trim()).filter(Boolean);
    const fresh = parts.filter((s, k) => parts.findIndex((x) => norm(x) === norm(s)) === k);
    if (fresh.length) move(fresh, g.id);
    setDrafts((d) => ({ ...d, [g.id]: "" }));
  };

  const remove = (s: string) => {
    onChange(groups.map((g) => ({ ...g, items: g.items.filter((x) => norm(x) !== norm(s)) })));
    setSelected((cur) => cur.filter((x) => norm(x) !== norm(s)));
  };

  // Dragging a selected skill drags the whole selection.
  const onDragStart = (e: DragEvent, s: string) => {
    const items = isSel(s) ? selected : [s];
    e.dataTransfer.setData(MIME, JSON.stringify(items));
    e.dataTransfer.effectAllowed = "move";
  };
  const dropProps = (target: string, before?: string) => ({
    onDragOver: (e: DragEvent) => {
      if (!e.dataTransfer.types.includes(MIME)) return;
      e.preventDefault();
      e.stopPropagation();
      setOver(target);
    },
    onDragLeave: () => setOver((o) => (o === target ? null : o)),
    onDrop: (e: DragEvent) => {
      const raw = e.dataTransfer.getData(MIME);
      if (!raw) return;
      e.preventDefault();
      e.stopPropagation();
      setOver(null);
      move(JSON.parse(raw) as string[], target, before);
    },
  });

  return (
    <div className="space-y-3">
      {groups.length === 0 && <p className="text-sm text-zinc-500">No skills yet.</p>}

      {groups.map((g, i) => (
        <div
          key={g.id}
          {...dropProps(g.id)}
          className={cx(
            "rounded-lg border p-3 transition-colors",
            over === g.id ? "border-violet-400 bg-violet-50/60 dark:border-violet-500/60 dark:bg-violet-500/10" : "border-zinc-200 dark:border-zinc-800",
          )}
        >
          <div className="mb-2 flex items-center gap-2">
            <Input
              value={g.name ?? ""}
              placeholder="Group name, e.g. Backend & APIs"
              aria-label="Group name"
              className="font-medium"
              onChange={(e) => setGroup(i, { name: e.target.value.trim() === "" ? null : e.target.value })}
            />
            <span className="shrink-0 text-xs text-zinc-400 tabular-nums" title="Skills in this group">
              {g.items.length}
            </span>
            <div className="flex items-center gap-0.5">
              <IconButton label="Move group up" disabled={i === 0} onClick={() => onChange(swap(groups, i, i - 1))}>
                <ArrowUp className="size-3.5" />
              </IconButton>
              <IconButton label="Move group down" disabled={i === groups.length - 1} onClick={() => onChange(swap(groups, i, i + 1))}>
                <ArrowDown className="size-3.5" />
              </IconButton>
              <IconButton
                label={g.items.length ? "Delete group and its skills" : "Delete group"}
                className="hover:text-rose-600"
                onClick={() => {
                  onChange(groups.filter((_, j) => j !== i));
                  setSelected((cur) => cur.filter((s) => !g.items.some((x) => norm(x) === norm(s))));
                }}
              >
                <Trash2 className="size-3.5" />
              </IconButton>
            </div>
          </div>

          <div className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-lg bg-white px-2 py-1.5 ring-1 ring-zinc-200 focus-within:ring-2 focus-within:ring-violet-500/60 dark:bg-zinc-950 dark:ring-zinc-800">
            {g.items.map((s) => (
              <span
                key={s}
                draggable
                onDragStart={(e) => onDragStart(e, s)}
                onDragEnd={() => setOver(null)}
                {...dropProps(g.id, s)}
                onClick={() => toggle(s)}
                title="Drag to another group, or click to select"
                className={cx(
                  "inline-flex cursor-grab items-center gap-1 rounded-md py-0.5 pr-1 pl-2 text-xs font-medium select-none active:cursor-grabbing",
                  isSel(s)
                    ? "bg-violet-600 text-white dark:bg-violet-500"
                    : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700",
                )}
              >
                {s}
                <button
                  type="button"
                  aria-label={`Remove ${s}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    remove(s);
                  }}
                  className={cx("rounded", isSel(s) ? "text-white/70 hover:text-white" : "text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-100")}
                >
                  <X className="size-3" />
                </button>
              </span>
            ))}
            <input
              value={drafts[g.id] ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                if (v.endsWith(",")) add(g, v);
                else setDrafts((d) => ({ ...d, [g.id]: v }));
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  add(g, drafts[g.id] ?? "");
                }
              }}
              onBlur={() => (drafts[g.id] ?? "").trim() && add(g, drafts[g.id] ?? "")}
              placeholder={g.items.length ? "Add…" : "Type a skill and press Enter, or drop skills here"}
              className="min-w-[8rem] flex-1 bg-transparent px-1 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none dark:text-zinc-100 dark:placeholder:text-zinc-600"
            />
          </div>
        </div>
      ))}

      {selected.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-zinc-100 px-3 py-2 text-sm dark:bg-zinc-800/60">
          <span className="text-zinc-700 dark:text-zinc-200">
            {selected.length} selected · move to
          </span>
          <select
            value=""
            onChange={(e) => e.target.value && move(selected, e.target.value)}
            className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            aria-label="Move selected skills to"
          >
            <option value="">Choose a group…</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name || "Untitled group"}
              </option>
            ))}
            <option value="new">+ New group</option>
          </select>
          <Button size="sm" variant="ghost" onClick={() => setSelected([])}>
            Clear selection
          </Button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={() => onChange([...groups, { id: newId(), name: null, items: [] }])}>
          Add group
        </Button>
        <div
          {...dropProps("new")}
          className={cx(
            "flex items-center gap-1.5 rounded-md border border-dashed px-3 py-1.5 text-xs transition-colors",
            over === "new" ? "border-violet-400 text-violet-700 dark:text-violet-300" : "border-zinc-300 text-zinc-400 dark:border-zinc-700",
          )}
        >
          <FolderPlus className="size-3.5" /> Drop skills here to start a new group
        </div>
      </div>
    </div>
  );
}

function swap<T>(arr: T[], a: number, b: number): T[] {
  const out = arr.slice();
  [out[a], out[b]] = [out[b], out[a]];
  return out;
}
