// Scan now: roles, location, date posted and the query text (prefilled from your roles, the
// location and your Search criteria; edit it freely). Everything else comes from Search criteria.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Radar, RotateCcw } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import type { DatePosted, ScanOut, ScanSelection, SearchCriteria, SearchPlanOut } from "../../lib/types";
import { Button, Input, Skeleton } from "../ui";
import { cx } from "../../lib/util";
import { Modal } from "../Modal";
import { Field, Select, SwitchRow } from "../settings/form";
import { LocationAdd } from "./LocationAdd";
import { RequestParams } from "./RequestParams";

// "auto" = no override: each search asks only for jobs posted since it last ran (Phase 2.7 E), so a
// request doesn't spend quota on jobs already found.
const DATE_OPTS: { value: DatePosted | "auto"; label: string }[] = [
  { value: "auto", label: "New since this search last ran" },
  { value: "today", label: "Past 24 hours" },
  { value: "3days", label: "Past 3 days" },
  { value: "week", label: "Past week" },
  { value: "month", label: "Past month" },
  { value: "all", label: "Any date" },
];
const DEFAULT_PLACE = ""; // no saved locations: the Search API country in Admin settings

const KIND_HEADING: Record<string, string> = {
  search: "Job search",
  board: "Company boards",
  feed: "Remote feeds · open to India",
};

export function ScanPicker({ open, onClose, onStarted }: { open: boolean; onClose: () => void; onStarted: (s: ScanOut) => void }) {
  const [criteria, setCriteria] = useState<SearchCriteria | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [combine, setCombine] = useState(false);
  const [place, setPlace] = useState(DEFAULT_PLACE);
  const [adding, setAdding] = useState(false);
  const [datePosted, setDatePosted] = useState<DatePosted | "auto">("auto");
  const [texts, setTexts] = useState<Record<number, string>>({});
  // Sources you unticked for this scan (the rest = every enabled source), and the enabled ones.
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [known, setKnown] = useState<string[]>([]);
  const [plan, setPlan] = useState<SearchPlanOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  // Load your criteria and preselect what an automatic scan would search.
  useEffect(() => {
    if (!open) return;
    setError(null);
    setPlan(null);
    setTexts({});
    setSkipped(new Set());
    setAdding(false);
    setDatePosted("week");
    void (async () => {
      try {
        const [settings, auto] = await Promise.all([api.getSearchSettings(), api.getSearchPlan()]);
        const c = settings.criteria;
        setCriteria(c);
        setPlace(c.locations[0] ?? DEFAULT_PLACE);
        const fromAuto = new Set<string>();
        for (const call of auto.calls) {
          const q = auto.queries.find((x) => x.id === call.query_id);
          for (const r of q?.roles.length ? q.roles : q ? [q.role] : []) fromAuto.add(r);
        }
        setChosen(fromAuto.size ? fromAuto : new Set(c.roles.slice(0, 1)));
        setCombine(c.auto_mode === "combined");
      } catch (e) {
        setError(errorMessage(e));
      }
    })();
  }, [open]);

  const roles = criteria?.roles ?? null;

  const selection = (): ScanSelection | null => {
    if (!roles) return null;
    const pick = roles.filter((r) => chosen.has(r));
    if (!pick.length) return null;
    const typed = Object.fromEntries(Object.entries(texts).filter(([, v]) => v.trim()));
    return {
      roles: pick,
      combine,
      locations: place ? [place] : [],
      ...(datePosted !== "auto" ? { date_posted: datePosted } : {}),
      ...(Object.keys(typed).length ? { query_texts: typed } : {}),
      ...(skipped.size ? { sources: known.filter((n) => !skipped.has(n)) } : {}),
    };
  };

  // Dry run of the current choice (calls nothing).
  useEffect(() => {
    if (!open) return;
    const sel = selection();
    if (!sel) {
      setPlan(null);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      api
        .planScan(sel)
        .then((p) => {
          if (!live) return;
          setPlan(p);
          setKnown(p.sources.filter((s) => s.enabled && s.configured).map((s) => s.name));
          setError(null);
        })
        .catch((e) => live && setError(errorMessage(e)));
    }, 300);
    return () => {
      live = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, roles, chosen, combine, place, datePosted, texts, skipped]);

  const toggle = (r: string, on: boolean) =>
    setChosen((s) => {
      const n = new Set(s);
      if (on) n.add(r);
      else n.delete(r);
      return n;
    });

  // A new location is saved to your Search criteria, then used for this scan.
  const addPlace = async (p: string) => {
    if (!criteria) return;
    try {
      const saved = await api.patchSearchSettings({ criteria: { ...criteria, locations: [...criteria.locations, p] } });
      setCriteria(saved.criteria);
      setPlace(p);
      setAdding(false);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const start = async () => {
    const sel = selection();
    if (!sel) return;
    setStarting(true);
    try {
      const s = await api.startScan(sel);
      onStarted(s);
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setStarting(false);
    }
  };

  const n = plan?.calls.length ?? 0;
  const picked = (kind: string) => (plan?.sources ?? []).filter((s) => s.kind === kind && s.chosen && !skipped.has(s.name));
  const companies = picked("board").reduce((n, s) => n + s.details.length, 0);
  const feedReads = picked("feed").reduce((n, s) => n + Math.max(1, s.details.length), 0);
  const scanLabel = [
    `${n} request${n === 1 ? "" : "s"}`,
    companies ? `${companies} compan${companies === 1 ? "y" : "ies"}` : "",
    feedReads ? `${feedReads} feed read${feedReads === 1 ? "" : "s"}` : "",
  ].filter(Boolean).join(" + ");
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Scan now"
      subtitle="Each request returns up to 10 jobs."
      footer={
        <>
          {plan && (
            <span className="mr-auto text-xs text-zinc-500">
              {plan.quota.today_allowance} left today · {Math.max(0, plan.quota.monthly_limit - plan.quota.month_used)} this month
            </span>
          )}
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" icon={<Radar className="size-4" />} loading={starting} disabled={!plan || !plan.fits_budget} onClick={() => void start()}>
            Scan ({scanLabel})
          </Button>
        </>
      }
    >
      {error && <p className="mb-3 text-sm text-rose-600/80 dark:text-rose-400/80">{error}</p>}
      {!roles || !criteria ? (
        <Skeleton className="h-32" />
      ) : roles.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No roles yet.{" "}
          <Link to="/job-search/settings#criteria" className="text-violet-700 hover:underline dark:text-violet-300" onClick={onClose}>
            Add Roles you want
          </Link>{" "}
          first.
        </p>
      ) : (
        <div className="space-y-5">
          <div>
            <div className="mb-2 flex items-center justify-between text-xs text-zinc-500">
              <span>Roles</span>
              <button type="button" className="hover:text-zinc-900 dark:hover:text-zinc-100" onClick={() => setChosen(chosen.size === roles.length ? new Set() : new Set(roles))}>
                {chosen.size === roles.length ? "Clear" : "All"}
              </button>
            </div>
            <ul className="divide-y divide-zinc-100 rounded-md border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
              {roles.map((r) => (
                <li key={r}>
                  <label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm text-zinc-800 dark:text-zinc-200">
                    <input type="checkbox" checked={chosen.has(r)} onChange={(e) => toggle(r, e.target.checked)} className="size-4 accent-violet-600" />
                    {r}
                  </label>
                </li>
              ))}
            </ul>
            {chosen.size > 1 && (
              <div className="mt-3">
                <SwitchRow label="One request for all chosen roles (OR)" hint="1 request instead of one per role; the 10 results are shared." checked={combine} onChange={setCombine} />
              </div>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Location" htmlFor="scan-place">
              <Select
                id="scan-place"
                value={adding ? "__add" : place}
                onChange={(e) => {
                  if (e.target.value === "__add") setAdding(true);
                  else {
                    setAdding(false);
                    setPlace(e.target.value);
                  }
                }}
              >
                {criteria.locations.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
                {criteria.locations.length === 0 && <option value={DEFAULT_PLACE}>Default country (Admin settings)</option>}
                <option value="__add">+ Add a location…</option>
              </Select>
            </Field>
            <Field label="Date posted" htmlFor="scan-date">
              <Select id="scan-date" value={datePosted} onChange={(e) => setDatePosted(e.target.value as DatePosted | "auto")}>
                {DATE_OPTS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          {adding && (
            <Field label="New location" hint="Saved to your Search criteria. A state or city goes into the query text; the country is sent as the country.">
              <LocationAdd existing={criteria.locations} onAdd={(p) => void addPlace(p)} />
            </Field>
          )}

          {plan && plan.sources.length > 0 && (
            <div>
              <div className="mb-2 text-xs text-zinc-500">Sources</div>
              <ul className="divide-y divide-zinc-100 rounded-md border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
                {plan.sources.flatMap((s, i) => {
                  const heading = i === 0 || plan.sources[i - 1].kind !== s.kind ? KIND_HEADING[s.kind] : undefined;
                  const usable = s.enabled && s.configured;
                  const row = (
                    <li key={s.name}>
                      <label className={cx("flex items-center gap-3 px-3 py-2 text-sm", usable ? "cursor-pointer text-zinc-800 dark:text-zinc-200" : "text-zinc-400")}>
                        <input
                          type="checkbox"
                          checked={usable && !skipped.has(s.name)}
                          disabled={!usable}
                          onChange={(e) =>
                            setSkipped((prev) => {
                              const n = new Set(prev);
                              if (e.target.checked) n.delete(s.name);
                              else n.add(s.name);
                              return n;
                            })
                          }
                          className="size-4 accent-violet-600"
                        />
                        <span className="min-w-0 flex-1">
                          {s.label}
                          {s.details.length > 0 && (
                            <span className="block truncate text-[11px] text-zinc-400" title={s.details.join(", ")}>
                              {s.details.slice(0, 4).join(", ")}
                              {s.details.length > 4 ? ` +${s.details.length - 4} more` : ""}
                            </span>
                          )}
                        </span>
                        <span className="shrink-0 text-right text-xs text-zinc-500 tabular-nums">{s.summary}</span>
                      </label>
                    </li>
                  );
                  return heading
                    ? [
                        <li key={`h-${s.kind}`} className="bg-zinc-50 px-3 py-1.5 text-[11px] font-semibold tracking-wider text-zinc-400 uppercase dark:bg-zinc-900">
                          {heading}
                        </li>,
                        row,
                      ]
                    : [row];
                })}
              </ul>
            </div>
          )}

          {plan &&
            plan.calls.map((c) => {
              const typed = texts[c.query_id];
              return (
                <div key={`${c.query_id}-${c.page}`}>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <label htmlFor={`q-${c.query_id}`} className="text-sm text-zinc-700 dark:text-zinc-300">
                      Query{plan.calls.length > 1 ? ` · request ${plan.calls.indexOf(c) + 1}` : ""}
                    </label>
                    {typed !== undefined && (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
                        onClick={() =>
                          setTexts((t) => {
                            const next = { ...t };
                            delete next[c.query_id];
                            return next;
                          })
                        }
                      >
                        <RotateCcw className="size-3" /> Default
                      </button>
                    )}
                  </div>
                  <Input
                    id={`q-${c.query_id}`}
                    value={typed ?? c.query}
                    placeholder={c.default_query}
                    maxLength={300}
                    onChange={(e) => setTexts((t) => ({ ...t, [c.query_id]: e.target.value }))}
                  />
                  <RequestParams params={c.params} className="mt-2 rounded-md bg-zinc-50 px-3 py-2 dark:bg-zinc-900" />
                </div>
              );
            })}
          {plan?.notes.map((x) => (
            <p key={x} className="text-xs text-amber-700 dark:text-amber-400">
              {x}
            </p>
          ))}
        </div>
      )}
    </Modal>
  );
}
