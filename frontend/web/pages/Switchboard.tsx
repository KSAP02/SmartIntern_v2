import type { ReactNode } from "react";
import { CheckCircle2, CircleAlert, FileCog, RefreshCw, Terminal } from "lucide-react";
import { api } from "../lib/api";
import { useResource } from "../lib/util";
import { Badge, Button, Card, ErrorBanner, PageHeader, Skeleton } from "../components/ui";

const COMPONENT_LABELS: Record<string, string> = {
  llm: "Language model",
  embeddings: "Embeddings",
  vectors: "Vector store (Milvus Lite)",
  database: "Database (SQLite)",
  storage: "File storage",
};

function show(v: unknown): ReactNode {
  if (v === null || v === undefined || v === "") return <span className="text-zinc-400">—</span>;
  if (Array.isArray(v)) return v.length ? v.join(", ") : <span className="text-zinc-400">—</span>;
  if (typeof v === "object") return <code className="text-xs">{JSON.stringify(v)}</code>;
  return String(v);
}

function KV({ rows }: { rows: [string, unknown][] }) {
  return (
    <dl className="divide-y divide-zinc-100 dark:divide-zinc-800">
      {rows.map(([k, v]) => (
        <div key={k} className="flex items-start justify-between gap-4 py-2.5 text-sm">
          <dt className="text-zinc-500 dark:text-zinc-400">{k}</dt>
          <dd className="text-right font-medium break-all text-zinc-800 dark:text-zinc-200">{show(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function tasksOf(llm: Record<string, unknown>): Record<string, Record<string, unknown>> {
  const t = llm.tasks;
  return t && typeof t === "object" ? (t as Record<string, Record<string, unknown>>) : {};
}

const pretty = (k: string) => k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export default function Switchboard() {
  const { data, error, loading, reload } = useResource(api.status);

  return (
    <div>
      <PageHeader
        title="Switchboard"
        subtitle="System status and the settings your intern is running with."
        actions={
          <Button icon={<RefreshCw className="size-4" />} onClick={() => void reload()}>
            Refresh
          </Button>
        }
      />
      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} onRetry={reload} />
        </div>
      )}
      {loading && !data && (
        <div className="space-y-4">
          <Skeleton className="h-56" />
          <Skeleton className="h-40" />
        </div>
      )}
      {data && (
        <div className="space-y-6">
          <Card className="p-6">
            <h2 className="mb-4 text-sm font-semibold text-zinc-900 dark:text-zinc-100">Components</h2>
            <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {Object.entries(data.components).map(([k, c]) => (
                <li key={k} className="flex items-start gap-3 py-3">
                  {c.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-500" /> : <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-500" />}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{COMPONENT_LABELS[k] ?? pretty(k)}</p>
                      <Badge tone={c.ok ? "green" : "amber"}>{c.ok ? "ready" : "needs attention"}</Badge>
                    </div>
                    <p className="mt-0.5 text-xs break-words text-zinc-500 dark:text-zinc-400">{c.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card className="p-6">
              <h2 className="mb-2 text-sm font-semibold text-zinc-900 dark:text-zinc-100">Language model</h2>
              <KV rows={Object.entries(data.llm).filter(([k]) => k !== "tasks").map(([k, v]) => [pretty(k), v])} />
              {Object.keys(tasksOf(data.llm)).length > 0 && (
                <div className="mt-4">
                  <h3 className="mb-2 text-xs font-semibold text-zinc-500">Per-task overrides</h3>
                  <div className="space-y-2">
                    {Object.entries(tasksOf(data.llm)).map(([task, params]) => (
                      <div key={task} className="rounded-lg bg-zinc-50 p-3 dark:bg-zinc-950">
                        <p className="mb-1 font-mono text-xs font-medium text-violet-700 dark:text-violet-300">{task}</p>
                        <div className="flex flex-wrap gap-1.5">
                          {Object.entries(params ?? {}).map(([k, v]) => (
                            <Badge key={k}>
                              {k} = {String(v)}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Card>
            <div className="space-y-6">
              <Card className="p-6">
                <h2 className="mb-2 text-sm font-semibold text-zinc-900 dark:text-zinc-100">Embeddings</h2>
                <KV rows={Object.entries(data.embedding).map(([k, v]) => [pretty(k), v])} />
              </Card>
              <Card className="p-6">
                <h2 className="mb-2 text-sm font-semibold text-zinc-900 dark:text-zinc-100">Limits</h2>
                <KV rows={Object.entries(data.limits).map(([k, v]) => [pretty(k), v])} />
              </Card>
            </div>
          </div>

          <Card className="p-6">
            <div className="flex items-start gap-3">
              <div className="flex size-8 items-center justify-center rounded-lg bg-violet-50 text-violet-600 dark:bg-violet-500/15 dark:text-violet-300">
                <FileCog className="size-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Tuning file</h2>
                  <Badge tone={data.config_loaded ? "green" : "amber"}>{data.config_loaded ? "loaded" : "not found, using defaults"}</Badge>
                </div>
                <p className="mt-1 font-mono text-xs break-all text-zinc-500">{data.config_file}</p>
                <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-400">
                  Models, temperature, reasoning effort and limits live in <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-800">settings/config.toml</code>. API keys stay in{" "}
                  <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-800">.env</code>. After editing, restart the backend:
                </p>
                <div className="mt-2 flex items-center gap-2 rounded-lg bg-zinc-900 px-3 py-2 font-mono text-xs text-zinc-100 dark:bg-zinc-950">
                  <Terminal className="size-3.5 text-zinc-500" />
                  docker compose restart backend
                </div>
              </div>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
