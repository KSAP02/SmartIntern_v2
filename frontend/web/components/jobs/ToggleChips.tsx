import { cx } from "../../lib/util";

const chip =
  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/60";
const on = "bg-violet-50 text-violet-700 ring-1 ring-violet-300 dark:bg-violet-500/15 dark:text-violet-300 dark:ring-violet-500/40";
const off =
  "text-zinc-600 ring-1 ring-zinc-200 hover:text-zinc-900 hover:ring-zinc-300 dark:text-zinc-400 dark:ring-zinc-800 dark:hover:text-zinc-100 dark:hover:ring-zinc-700";

/**
 * Multi-select as toggle chips with an "All" chip. All selected ⇔ empty array:
 * picking a value deselects All; deselecting the last value re-selects All.
 */
export function ToggleChips<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T[];
  onChange: (v: T[]) => void;
  options: { value: T; label: string }[];
  label: string;
}) {
  const all = value.length === 0;
  const toggle = (v: T) => {
    const next = value.includes(v) ? value.filter((x) => x !== v) : [...value, v];
    // keep option order stable
    onChange(options.map((o) => o.value).filter((o) => next.includes(o)));
  };
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      <button type="button" aria-pressed={all} onClick={() => onChange([])} className={cx(chip, all ? on : off)}>
        All
      </button>
      {options.map((o) => {
        const sel = value.includes(o.value);
        return (
          <button key={o.value} type="button" aria-pressed={sel} onClick={() => toggle(o.value)} className={cx(chip, sel ? on : off)}>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Single-select chips (used for quick filters). `null` = All. */
export function FilterChips<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T | null;
  onChange: (v: T | null) => void;
  options: { value: T; label: string }[];
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      <button type="button" aria-pressed={value === null} onClick={() => onChange(null)} className={cx(chip, value === null ? on : off)}>
        All
      </button>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(value === o.value ? null : o.value)}
          className={cx(chip, value === o.value ? on : off)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Thin horizontal bar, 0–100. */
export function MiniBar({ value, className }: { value: number; className?: string }) {
  return (
    <span className={cx("inline-block h-1 w-12 overflow-hidden rounded-full bg-zinc-200 align-middle dark:bg-zinc-800", className)}>
      <span className="block h-full rounded-full bg-violet-600 dark:bg-violet-400" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </span>
  );
}
