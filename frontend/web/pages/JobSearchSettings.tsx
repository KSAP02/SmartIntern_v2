import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import type {
  ApplyPreset,
  Category,
  Compensation,
  SalaryPeriod,
  SearchCriteria,
  SearchSettings,
  Seniority,
  SettingsSection,
  Workplace,
} from "../lib/types";
import { useResource } from "../lib/util";
import { Button, ErrorBanner, PageHeader, Segmented, Skeleton } from "../components/ui";
import { ChipInput } from "../components/ChipInput";
import { LocationAdd } from "../components/jobs/LocationAdd";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { ToggleChips } from "../components/jobs/ToggleChips";
import { CATEGORY_LABEL, PAY_LABEL, PERIOD_LABEL, SENIORITY_LABEL } from "../components/jobs/format";
import { SearchPlan } from "../components/jobs/SearchPlan";
import { Field, MoreOptions, NumInput, Section, SectionNav, Select, SwitchRow, same } from "../components/settings/form";

const SECTIONS: { id: SettingsSection | "plan"; label: string }[] = [
  { id: "criteria", label: "Search criteria" },
  { id: "plan", label: "Search plan" },
  { id: "preset", label: "Apply preset" },
];

const AUTO_MODE_HINT: Record<SearchCriteria["auto_mode"], string> = {
  rotate: "One role per request, taking turns: each scan searches the next roles (up to requests per scan).",
  each: "Every included role, one request each, every scan (costs one request per role).",
  combined: "All included roles in ONE request (“A OR B in India”): 1 request per scan; the 10 results are shared.",
};
/** Marks an option JSearch applies itself (so fewer of each request's 10 results are wasted). */
const SENT = " Sent to JSearch.";

const SECTION_LABEL: Record<SettingsSection, string> = {
  criteria: "Search criteria",
  preset: "Apply preset",
};

const CATEGORY_OPTS = (Object.keys(CATEGORY_LABEL) as Category[]).map((v) => ({ value: v, label: CATEGORY_LABEL[v] }));
const WORKPLACE_OPTS: { value: Workplace; label: string }[] = [
  { value: "remote", label: "Remote / WFH" },
  { value: "hybrid", label: "Hybrid" },
  { value: "onsite", label: "On-site" },
];
const PAY_OPTS = (Object.keys(PAY_LABEL) as Compensation[]).map((v) => ({ value: v, label: PAY_LABEL[v] }));
const SENIORITY_OPTS = (Object.keys(SENIORITY_LABEL) as Seniority[]).map((v) => ({ value: v, label: SENIORITY_LABEL[v] }));
const CURRENCIES = ["INR", "USD", "EUR", "GBP"];
const PERIODS = Object.keys(PERIOD_LABEL) as SalaryPeriod[];

// ── Summaries ──────────────────────────────────────────────────────────────────

function criteriaSummary(c: SearchCriteria): string {
  const parts: string[] = [];
  if (c.roles.length) parts.push(`roles: ${c.roles.join(", ")}`);
  if (c.job_types.length) parts.push(c.job_types.map((t) => CATEGORY_LABEL[t]).join(", "));
  if (c.workplace.length) parts.push(c.workplace.map((w) => WORKPLACE_OPTS.find((o) => o.value === w)?.label ?? w).join(", "));
  if (c.locations.length) parts.push(c.locations.join(", "));
  return parts.length ? `Gathering: ${parts.join(" · ")} — everything else All` : "Gathering: everything (all options are All)";
}

function presetSummary(p: ApplyPreset): string {
  const parts: string[] = [];
  if (p.pay.length) parts.push(p.pay.map((x) => PAY_LABEL[x]).join(", "));
  if (p.salary_min != null || p.salary_max != null) {
    const r = p.salary_min != null && p.salary_max != null ? `${p.salary_min}–${p.salary_max}` : p.salary_min != null ? `≥ ${p.salary_min}` : `≤ ${p.salary_max}`;
    parts.push(`${r} ${p.salary_currency} / ${p.salary_period}`);
  }
  if (p.min_fit != null) parts.push(`≥ ${p.min_fit}% must-haves`);
  if (p.seniority.length) parts.push(p.seniority.map((s) => SENIORITY_LABEL[s]).join(", "));
  if (p.max_years_experience != null) parts.push(`≤ ${p.max_years_experience} yrs asked`);
  if (p.needs_visa_sponsorship) parts.push("sponsors visas");
  if (p.max_internship_months != null) parts.push(`internships ≤ ${p.max_internship_months} mo`);
  if (p.only_companies.length) parts.push(`only ${p.only_companies.join(", ")}`);
  const base = parts.length ? `Preset: ${parts.join(" · ")} — everything else All` : "Preset: everything fits (all options are All)";
  return p.include_unknown ? base : `${base} · unknown details excluded`;
}

// ── Sections ───────────────────────────────────────────────────────────────────

function CriteriaFields({ v, set }: { v: SearchCriteria; set: (v: SearchCriteria) => void }) {
  return (
    <>
      <Field label="Roles you want" hint={`One search per role (and per place). A job is kept only if its title matches one of these.${SENT}`}>
        <ChipInput value={v.roles} onChange={(roles) => set({ ...v, roles })} placeholder="e.g. Backend Engineer, AI Engineer — press Enter" />
      </Field>
      {v.roles.length > 0 && (
        <Field label="Roles in automatic scans" hint="Which roles automatic scans search (none ticked = all). Scan now lets you choose each time.">
          <ToggleChips
            label="Roles in automatic scans"
            value={v.auto_roles.filter((r) => v.roles.some((x) => x.toLowerCase() === r.toLowerCase()))}
            onChange={(auto_roles) => set({ ...v, auto_roles })}
            options={v.roles.map((r) => ({ value: r, label: r }))}
          />
        </Field>
      )}
      {v.roles.length > 0 && (
        <Field label="How automatic scans search" hint={AUTO_MODE_HINT[v.auto_mode]}>
          <Segmented
            value={v.auto_mode}
            onChange={(auto_mode) => set({ ...v, auto_mode })}
            options={[
              { value: "rotate", label: "Rotate" },
              { value: "each", label: "Each role" },
              { value: "combined", label: "Combined (OR)" },
            ]}
          />
        </Field>
      )}
      <Field label="Job types" hint={`Empty = all.${SENT} Only Internship also adds “internship” to the default query. Jobs are never removed for their type: filter them on the Jobs page.`}>
        <ToggleChips label="Job types" value={v.job_types} onChange={(job_types) => set({ ...v, job_types })} options={CATEGORY_OPTS} />
      </Field>
      <Field label="Workplace" hint="Remote only is sent to JSearch (remote jobs only); other choices send nothing. Filter by workplace on the Jobs page.">
        <ToggleChips label="Workplace" value={v.workplace} onChange={(workplace) => set({ ...v, workplace })} options={WORKPLACE_OPTS} />
      </Field>
      <Field label="Locations" hint="Pick a country and, optionally, a state or city in it. The country is sent to JSearch; a state or city goes into the query text (“AI Engineer in Karnataka, India”). Scan now lets you choose one per scan; automatic scans search each. Location never removes a job: Matches shows where each job is. Empty = the Search API country in Admin settings.">
        <div className="space-y-2">
          <ChipInput value={v.locations} onChange={(locations) => set({ ...v, locations })} placeholder="Or type one and press Enter" />
          <LocationAdd existing={v.locations} onAdd={(p) => set({ ...v, locations: [...v.locations, p] })} />
        </div>
      </Field>
    </>
  );
}

function PresetFields({ v, set }: { v: ApplyPreset; set: (v: ApplyPreset) => void }) {
  return (
    <>
      <Field label="Pay">
        <ToggleChips label="Pay" value={v.pay} onChange={(pay) => set({ ...v, pay })} options={PAY_OPTS} />
      </Field>
      <Field label="Salary range" hint="Leave both empty for All. Jobs in another currency or period are compared only when they can be converted.">
        <div className="flex flex-wrap items-center gap-2">
          <NumInput ariaLabel="Minimum salary" nullable min={0} placeholder="Min" value={v.salary_min} onChange={(salary_min) => set({ ...v, salary_min })} className="w-28" />
          <span className="text-zinc-400">–</span>
          <NumInput ariaLabel="Maximum salary" nullable min={0} placeholder="Max" value={v.salary_max} onChange={(salary_max) => set({ ...v, salary_max })} className="w-28" />
          <Select aria-label="Currency" value={v.salary_currency} onChange={(e) => set({ ...v, salary_currency: e.target.value })}>
            {(CURRENCIES.includes(v.salary_currency) ? CURRENCIES : [v.salary_currency, ...CURRENCIES]).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
          <Select aria-label="Salary period" value={v.salary_period} onChange={(e) => set({ ...v, salary_period: e.target.value as SalaryPeriod })}>
            {PERIODS.map((p) => (
              <option key={p} value={p}>
                per {PERIOD_LABEL[p]}
              </option>
            ))}
          </Select>
        </div>
      </Field>
      <Field label="Minimum fit" hint="Share of the job's must-haves your memory covers (a partial match counts half).">
        <div className="flex flex-wrap items-center gap-3">
          <Segmented
            value={v.min_fit == null ? "all" : "set"}
            onChange={(x) => set({ ...v, min_fit: x === "all" ? null : (v.min_fit ?? 60) })}
            options={[
              { value: "all", label: "All" },
              { value: "set", label: "At least" },
            ]}
          />
          {v.min_fit != null && (
            <div className="flex flex-1 items-center gap-3">
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={v.min_fit}
                aria-label="Minimum fit percent"
                onChange={(e) => set({ ...v, min_fit: Number(e.target.value) })}
                className="max-w-56 flex-1 accent-violet-600"
              />
              <span className="w-10 text-sm text-zinc-700 tabular-nums dark:text-zinc-300">{v.min_fit}%</span>
            </div>
          )}
        </div>
      </Field>
      <SwitchRow
        label="Include jobs with unknown details"
        hint="When a job doesn't state something (pay, seniority…), count it as fitting instead of leaving it out."
        checked={v.include_unknown}
        onChange={(include_unknown) => set({ ...v, include_unknown })}
      />
      <MoreOptions>
        <Field label="Seniority">
          <ToggleChips label="Seniority" value={v.seniority} onChange={(seniority) => set({ ...v, seniority })} options={SENIORITY_OPTS} />
        </Field>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Max years of experience asked" htmlFor="max-years" hint="Empty = All.">
            <NumInput id="max-years" nullable min={0} step={0.5} placeholder="All" value={v.max_years_experience} onChange={(max_years_experience) => set({ ...v, max_years_experience })} />
          </Field>
          <Field label="Max internship length (months)" htmlFor="max-months" hint="Empty = All.">
            <NumInput id="max-months" nullable min={0} step={1} placeholder="All" value={v.max_internship_months} onChange={(max_internship_months) => set({ ...v, max_internship_months })} />
          </Field>
        </div>
        <SwitchRow
          label="I need visa sponsorship"
          hint="Jobs that say they don't sponsor go to Other relevant."
          checked={v.needs_visa_sponsorship}
          onChange={(needs_visa_sponsorship) => set({ ...v, needs_visa_sponsorship })}
        />
        <Field label="Only these companies" hint="Empty = any company.">
          <ChipInput value={v.only_companies} onChange={(only_companies) => set({ ...v, only_companies })} placeholder="e.g. a dream employer" />
        </Field>
      </MoreOptions>
    </>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function JobSearchSettings() {
  const toast = useToast();
  const location = useLocation();
  const { data: saved, setData: setSaved, error, loading, reload } = useResource(api.getSearchSettings);
  const [draft, setDraft] = useState<SearchSettings | null>(null);
  const [saving, setSaving] = useState<SettingsSection | null>(null);
  const [resetting, setResetting] = useState<SettingsSection | null>(null);
  const [confirmReset, setConfirmReset] = useState<SettingsSection | null>(null);
  const plan = useResource(api.getSearchPlan);

  useEffect(() => {
    if (saved && !draft) setDraft(saved);
  }, [saved, draft]);

  // honour #section links once content exists
  useEffect(() => {
    if (!draft || !location.hash) return;
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!draft, location.hash]);

  const dirty = (s: SettingsSection) => !!saved && !!draft && !same(saved[s], draft[s]);

  /** Server state for one section replaces the draft for that section only (other unsaved edits stay). */
  const accept = (s: SettingsSection, out: SearchSettings) => {
    setSaved(out);
    setDraft((d) => (d ? { ...d, [s]: out[s] } : out));
  };

  const save = async (s: SettingsSection) => {
    if (!draft) return;
    setSaving(s);
    try {
      const out = await api.patchSearchSettings({ [s]: draft[s] });
      accept(s, out);
      toast.success(`${SECTION_LABEL[s]} saved`, s === "criteria" ? "Jobs already gathered are re-checked; the search plan below is updated." : undefined);
      if (s === "criteria") void plan.reload();
    } catch (e) {
      toast.error(`Couldn't save ${SECTION_LABEL[s].toLowerCase()}`, errorMessage(e));
    } finally {
      setSaving(null);
    }
  };

  const reset = async (s: SettingsSection) => {
    setConfirmReset(null);
    setResetting(s);
    try {
      const out = await api.resetSearchSettings(s);
      accept(s, out);
      toast.success(`${SECTION_LABEL[s]} reset to defaults`);
      if (s === "criteria") void plan.reload();
    } catch (e) {
      toast.error("Couldn't reset", errorMessage(e));
    } finally {
      setResetting(null);
    }
  };

  function set<K extends SettingsSection>(k: K, v: SearchSettings[K]) {
    setDraft((d) => (d ? { ...d, [k]: v } : d));
  }

  const common = (s: SettingsSection) => ({
    dirty: dirty(s),
    saving: saving === s || resetting === s,
    onSave: () => void save(s),
    onReset: () => setConfirmReset(s),
  });

  return (
    <div>
      <PageHeader
        title="Search Settings"
        subtitle={
          <>
            What to search for, what each scan will send to JSearch, and how to sort the results. The request budget, schedule, retention and matching are in{" "}
            <Link to="/admin" className="inline-flex items-center gap-0.5 text-violet-700 hover:underline dark:text-violet-300">
              Admin settings <ArrowRight className="size-3" />
            </Link>
          </>
        }
      />

      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} onRetry={reload} />
        </div>
      )}

      {loading && !draft && (
        <div className="space-y-4">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      )}

      {draft && (
        <div className="grid gap-8 lg:grid-cols-[9.5rem_minmax(0,1fr)]">
          <SectionNav sections={SECTIONS} dirty={(id) => id !== "plan" && dirty(id as SettingsSection)} />

          <div className="min-w-0 space-y-6">
            <Section id="criteria" title="Search criteria" description="Before gathering: what to collect at all. Jobs with unknown values are always kept." summary={criteriaSummary(draft.criteria)} {...common("criteria")}>
              <CriteriaFields v={draft.criteria} set={(v) => set("criteria", v)} />
            </Section>

            <Section
              id="plan"
              title="Search plan"
              description={dirty("criteria") ? "Save the search criteria to see their plan. Building the plan calls nothing (a dry run)." : "Exactly what the next scan sends to JSearch, and what it costs. Building the plan calls nothing (a dry run)."}
            >
              <SearchPlan plan={plan.data} error={plan.error} loading={plan.loading} reload={() => void plan.reload()} />
            </Section>

            <Section
              id="preset"
              title="Apply preset"
              description="Before applying. Sorts gathered jobs into Fits your preset / Other relevant; nothing is removed."
              summary={presetSummary(draft.preset)}
              {...common("preset")}
            >
              <PresetFields v={draft.preset} set={(v) => set("preset", v)} />
            </Section>
          </div>
        </div>
      )}

      <Modal
        open={confirmReset !== null}
        onClose={() => setConfirmReset(null)}
        title={`Reset ${confirmReset ? SECTION_LABEL[confirmReset].toLowerCase() : ""}?`}
        footer={
          <>
            <Button onClick={() => setConfirmReset(null)}>Cancel</Button>
            <Button variant="primary" onClick={() => confirmReset && void reset(confirmReset)}>
              Reset to defaults
            </Button>
          </>
        }
      >
        <p className="text-sm text-zinc-600 dark:text-zinc-400">This section goes back to the defaults from config.toml. Other sections are not touched.</p>
      </Modal>
    </div>
  );
}
