import { useState } from "react";
import { X } from "lucide-react";
import { cx } from "../lib/util";

/** Edit a list of short strings as chips. Enter or comma adds; Backspace on empty removes the last. */
export function ChipInput({
  value,
  onChange,
  placeholder = "Type and press Enter",
  suggestions,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  suggestions?: string[];
}) {
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const parts = raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .filter((s) => !value.some((v) => v.toLowerCase() === s.toLowerCase()));
    if (parts.length) onChange([...value, ...parts]);
    setDraft("");
  };

  const unused = (suggestions ?? []).filter((s) => !value.includes(s));

  return (
    <div>
      <div
        className={cx(
          "flex min-h-10 flex-wrap items-center gap-1.5 rounded-lg bg-white px-2 py-1.5 ring-1 ring-zinc-200 transition-shadow duration-150 focus-within:ring-2 focus-within:ring-violet-500/60 dark:bg-zinc-950 dark:ring-zinc-800",
        )}
      >
        {value.map((v, i) => (
          <span
            key={`${v}-${i}`}
            className="inline-flex items-center gap-1 rounded-md bg-zinc-100 py-0.5 pr-1 pl-2 text-xs font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200"
          >
            {v}
            <button
              type="button"
              aria-label={`Remove ${v}`}
              onClick={() => onChange(value.filter((_, j) => j !== i))}
              className="rounded text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-100"
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          value={draft}
          onChange={(e) => {
            if (e.target.value.endsWith(",")) add(e.target.value);
            else setDraft(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(draft);
            } else if (e.key === "Backspace" && !draft && value.length) {
              onChange(value.slice(0, -1));
            }
          }}
          onBlur={() => draft.trim() && add(draft)}
          placeholder={value.length ? "" : placeholder}
          className="min-w-[8rem] flex-1 bg-transparent px-1 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none dark:text-zinc-100 dark:placeholder:text-zinc-600"
        />
      </div>
      {unused.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {unused.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onChange([...value, s])}
              className="rounded-md px-2 py-0.5 text-xs text-zinc-500 ring-1 ring-zinc-200 ring-dashed transition-colors hover:bg-violet-50 hover:text-violet-700 dark:text-zinc-400 dark:ring-zinc-700 dark:hover:bg-violet-500/10 dark:hover:text-violet-300"
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
