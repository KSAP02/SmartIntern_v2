import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cx } from "../lib/util";

type Kind = "success" | "error" | "info";
interface ToastItem {
  id: number;
  kind: Kind;
  title: string;
  body?: string;
}
interface ToastApi {
  success: (title: string, body?: string) => void;
  error: (title: string, body?: string) => void;
  info: (title: string, body?: string) => void;
}

const Ctx = createContext<ToastApi | null>(null);
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const push = useCallback(
    (kind: Kind, title: string, body?: string) => {
      const id = ++seq;
      setItems((xs) => [...xs.slice(-3), { id, kind, title, body }]);
      window.setTimeout(() => dismiss(id), kind === "error" ? 7000 : 3500);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (t, b) => push("success", t, b),
      error: (t, b) => push("error", t, b),
      info: (t, b) => push("info", t, b),
    }),
    [push],
  );

  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
        {items.map((t) => (
          <div
            key={t.id}
            role="status"
            className="toast-in pointer-events-auto flex items-start gap-3 rounded-xl bg-white p-3.5 shadow-lg ring-1 shadow-zinc-900/10 ring-zinc-200 dark:bg-zinc-900 dark:ring-zinc-800"
          >
            {t.kind === "success" && <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-500" />}
            {t.kind === "error" && <XCircle className="mt-0.5 size-4 shrink-0 text-rose-500" />}
            {t.kind === "info" && <Info className="mt-0.5 size-4 shrink-0 text-violet-500" />}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{t.title}</p>
              {t.body && <p className={cx("mt-0.5 text-xs break-words text-zinc-500 dark:text-zinc-400")}>{t.body}</p>}
            </div>
            <button onClick={() => dismiss(t.id)} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200" aria-label="Dismiss">
              <X className="size-4" />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): ToastApi {
  const c = useContext(Ctx);
  if (!c) throw new Error("useToast outside ToastProvider");
  return c;
}
