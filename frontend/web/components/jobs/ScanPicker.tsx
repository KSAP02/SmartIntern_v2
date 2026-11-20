// Scan now: roles, location, date posted and the query text (prefilled from your roles, the
// location and your Search criteria; edit it freely). Everything else comes from Search criteria.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Radar, RotateCcw } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import type { DatePosted, ScanOut, ScanSelection, SearchCriteria, SearchPlanOut } from "../../lib/types";
import { Button, Input, Skeleton } from "../ui";
import { Modal } from "../Modal";
import { Field, Select, SwitchRow } from "../settings/form";
import { LocationAdd } from "./LocationAdd";
import { RequestParams } from "./RequestParams";

const DATE_OPTS: { value: DatePosted; label: string }[] = [
  { value: "today", label: "Past 24 hours" },
  { value: "3days", label: "Past 3 days" },
  { value: "week", label: "Past week" },
  { value: "month", label: "Past month" },
  { value: "all", label: "Any date" },
];
const DEFAULT_PLACE = ""; // no saved locations: the Search API country in Admin settings

export function ScanPicker({ open, onClose, onStarted }: { open: boolean; onClose: () => void; onStarted: (s: ScanOut) => void }) {
  const [criteria, setCriteria] = useState<SearchCriteria | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [combine, setCombine] = useState(false);
  const [place, setPlace] = useState(DEFAULT_PLACE);
  const [adding, setAdding] = useState(false);
  const [datePosted, setDatePosted] = useState<DatePosted>("week");
  const [texts, setTexts] = useState<Record<number, string>>({});
  const [plan, setPlan] = useState<SearchPlanOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  // Load your criteria and preselect what an automatic scan would search.
  useEffect(() => {
    if (!open) return;
    setError(null);
    setPlan(null);
    setTexts({});
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
      date_posted: datePosted,
      ...(Object.keys(typed).length ? { query_texts: typed } : {}),
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
          setError(null);
        })
        .catch((e) => live && setError(errorMessage(e)));
    }, 300);
    return () => {
      live = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, roles, chosen, combine, place, datePosted, texts]);

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
          <Button variant="primary" icon={<Radar className="size-4" />} loading={starting} disabled={!plan || !plan.fits_budget || n === 0} onClick={() => void start()}>
            Scan ({n} request{n === 1 ? "" : "s"})
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
              <Select id="scan-date" value={datePosted} onChange={(e) => setDatePosted(e.target.value as DatePosted)}>
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
