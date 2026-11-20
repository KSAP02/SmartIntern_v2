// Form pieces shared by Search Settings and Admin settings.
import { useEffect, useState } from "react";
import type { ReactNode, SelectHTMLAttributes } from "react";
import { ChevronDown, ChevronRight, RotateCcw } from "lucide-react";
import { cx } from "../../lib/util";
import { Button, Card, Input, Label, Toggle } from "../ui";

const selectCls =
  "h-10 rounded-md border border-zinc-300 bg-white/80 px-2 text-sm text-zinc-900 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/15 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";

export function Select({ className, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...rest} className={cx(selectCls, className)} />;
}

/** Number input that keeps its own text while typing. Empty → null when `nullable`, else ignored. */
export function NumInput({
  value,
  onChange,
  nullable,
  min,
  max,
  step,
  placeholder,
  className,
  id,
  ariaLabel,
}: {
  value: number | null;
  onChange: (v: number | null) => void;
  nullable?: boolean;
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
  className?: string;
  id?: string;
  ariaLabel?: string;
}) {
  const [text, setText] = useState(value == null ? "" : String(value));
  useEffect(() => {
    setText((t) => (t !== "" && Number(t) === value ? t : value == null ? "" : String(value)));
  }, [value]);
  return (
    <Input
      id={id}
      aria-label={ariaLabel}
      type="number"
      inputMode="decimal"
      min={min}
      max={max}
      step={step}
      placeholder={placeholder}
      value={text}
      className={cx("tabular-nums", className)}
      onChange={(e) => {
        const t = e.target.value;
        setText(t);
        if (t.trim() === "") {
          if (nullable) onChange(null);
          return;
        }
        const n = Number(t);
        if (Number.isFinite(n)) onChange(n);
      }}
      onBlur={() => setText(value == null ? "" : String(value))}
    />
  );
}

export function Field({ label, htmlFor, hint, children, className }: { label: string; htmlFor?: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      {htmlFor ? (
        <label htmlFor={htmlFor} className="block">
          <Label>{label}</Label>
        </label>
      ) : (
        <Label>{label}</Label>
      )}
      {children}
      {hint && <p className="mt-1 text-[11px] leading-snug text-zinc-400 dark:text-zinc-500">{hint}</p>}
    </div>
  );
}

export function SwitchRow({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="text-sm text-zinc-800 dark:text-zinc-200">{label}</p>
        {hint && <p className="mt-0.5 text-[11px] text-zinc-400 dark:text-zinc-500">{hint}</p>}
      </div>
      <Toggle checked={checked} onChange={onChange} label={label} />
    </div>
  );
}

export function MoreOptions({ children, label = "More options" }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t border-zinc-100 pt-4 dark:border-zinc-800">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs font-medium text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
      >
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        {label}
      </button>
      {open && <div className="mt-4 space-y-5">{children}</div>}
    </div>
  );
}

export function Section({
  id,
  title,
  description,
  summary,
  children,
  dirty,
  saving,
  onSave,
  onReset,
  extraFooter,
}: {
  id: string;
  title: string;
  description?: ReactNode;
  summary?: string;
  children: ReactNode;
  dirty?: boolean;
  saving?: boolean;
  onSave?: () => void;
  onReset?: () => void;
  extraFooter?: ReactNode;
}) {
  return (
    <Card id={id} className="scroll-mt-8">
      <div className="border-b border-zinc-100 px-5 py-4 dark:border-zinc-800">
        <h2 className="flex items-center gap-2 font-serif text-lg text-zinc-900 dark:text-zinc-50">
          {title}
          {dirty && !onSave && <span className="size-1.5 rounded-full bg-violet-600 dark:bg-violet-400" title="Unsaved changes" />}
        </h2>
        {description && <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{description}</p>}
        {summary && <p className="mt-2 text-xs text-zinc-700 dark:text-zinc-300">{summary}</p>}
      </div>
      <div className="space-y-5 px-5 py-5">{children}</div>
      {(onSave || onReset || extraFooter) && (
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-zinc-100 px-5 py-3 dark:border-zinc-800">
          {extraFooter && <div className="mr-auto">{extraFooter}</div>}
          {onReset && (
            <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} onClick={onReset}>
              Reset to defaults
            </Button>
          )}
          {onSave && (
            <Button size="sm" variant="primary" disabled={!dirty} loading={saving} onClick={onSave}>
              Save
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}

/** Left-hand section index for long settings pages (desktop only). */
export function SectionNav({ sections, dirty }: { sections: { id: string; label: string }[]; dirty?: (id: string) => boolean }) {
  return (
    <nav aria-label="Settings sections" className="hidden lg:block">
      <ul className="sticky top-8 space-y-1 text-xs">
        {sections.map((s) => (
          <li key={s.id}>
            <a
              href={`#${s.id}`}
              onClick={(e) => {
                e.preventDefault();
                document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
                history.replaceState(null, "", `#${s.id}`);
              }}
              className="flex items-center gap-1.5 py-1 text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
            >
              {s.label}
              {dirty?.(s.id) && <span className="size-1.5 rounded-full bg-violet-600 dark:bg-violet-400" title="Unsaved changes" />}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
