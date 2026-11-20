import { useEffect } from "react";
import type { ReactNode } from "react";
import { X } from "lucide-react";
import { cx } from "../lib/util";
import { IconButton } from "./ui";

/** Centered dialog (`side=false`) or right-hand drawer (`side=true`). Closes on Esc and backdrop click. */
export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  side = false,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  side?: boolean;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div className="fade-in absolute inset-0 bg-zinc-950/40-[2px]" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        className={cx(
          "absolute flex flex-col bg-white shadow-lg ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-zinc-800",
          side
            ? "slide-in inset-y-0 right-0 w-full max-w-xl"
            : cx(
                "pop-in top-1/2 left-1/2 max-h-[88vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl",
                wide ? "max-w-3xl" : "max-w-lg",
              ),
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-zinc-100 px-6 py-4 dark:border-zinc-800">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-zinc-900 dark:text-zinc-50">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{subtitle}</p>}
          </div>
          <IconButton label="Close" onClick={onClose}>
            <X className="size-4" />
          </IconButton>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-zinc-100 px-6 py-3.5 dark:border-zinc-800">{footer}</div>
        )}
      </div>
    </div>
  );
}
