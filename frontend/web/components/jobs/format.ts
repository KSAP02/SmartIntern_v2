import type { Category, Compensation, JobCard, SalaryPeriod, ScanPhase, Seniority, QueryWording, Workplace } from "../../lib/types";

export const CATEGORY_LABEL: Record<Category, string> = {
  internship: "Internship",
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  freelance: "Freelance",
};
export const WORKPLACE_LABEL: Record<Workplace, string> = { remote: "Remote", hybrid: "Hybrid", onsite: "On-site" };
export const PAY_LABEL: Record<Compensation, string> = { paid: "Paid", stipend: "Stipend", unpaid: "Unpaid" };
export const SENIORITY_LABEL: Record<Seniority, string> = { intern: "Intern", entry: "Entry", mid: "Mid", senior: "Senior", lead: "Lead" };
export const PERIOD_LABEL: Record<SalaryPeriod, string> = { year: "year", month: "month", week: "week", day: "day", hour: "hour" };
export const PHASE_LABEL: Record<ScanPhase, string> = {
  fetching: "Fetching",
  processing: "Processing",
  mapping: "Mapping",
  pruning: "Pruning",
  done: "Done",
  failed: "Failed",
};

/** Human label for a breakdown key (category / workplace / country code). */
export function valueLabel(group: string, key: string): string {
  if (group === "category") return CATEGORY_LABEL[key as Category] ?? key;
  if (group === "workplace") return WORKPLACE_LABEL[key as Workplace] ?? key;
  if (key === "" || key === "unknown" || key === "null") return "Unknown";
  return key;
}

const SYMBOL: Record<string, string> = { INR: "₹", USD: "$", EUR: "€", GBP: "£" };

function compact(n: number): string {
  const a = Math.abs(n);
  const trim = (x: number) => (x >= 100 ? Math.round(x).toString() : x.toFixed(1).replace(/\.0$/, ""));
  if (a >= 1_000_000) return `${trim(n / 1_000_000)}M`;
  if (a >= 1_000) return `${trim(n / 1_000)}k`;
  return trim(n);
}

/** "₹25k–30k / month", "$90k+ / year", "up to €40k / year", or "Paid" / "Stipend" / "Unpaid". */
export function formatPay(j: Pick<JobCard, "salary_min" | "salary_max" | "salary_currency" | "salary_period" | "compensation_type">): string | null {
  const { salary_min: lo, salary_max: hi } = j;
  if (lo != null || hi != null) {
    const cur = j.salary_currency ?? "";
    const sym = SYMBOL[cur.toUpperCase()];
    const money = (n: number) => (sym ? `${sym}${compact(n)}` : `${compact(n)}${cur ? ` ${cur}` : ""}`);
    let range: string;
    if (lo != null && hi != null && lo !== hi) range = sym ? `${sym}${compact(lo)}–${compact(hi)}` : `${compact(lo)}–${money(hi)}`;
    else if (lo != null && hi != null) range = money(lo);
    else if (lo != null) range = `${money(lo)}+`;
    else range = `up to ${money(hi as number)}`;
    return j.salary_period ? `${range} / ${j.salary_period}` : range;
  }
  return j.compensation_type ? PAY_LABEL[j.compensation_type] : null;
}

function toDate(iso: string): Date {
  return new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
}

/** "today", "yesterday", "3d ago", "5w ago". */
export function foundAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = toDate(iso);
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((start(new Date()) - start(d)) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return `${days}d ago`;
  if (days < 60) return `${Math.round(days / 7)}w ago`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** "07:00" or "Tue 07:00" for a datetime that isn't today. */
export function clockTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = toDate(iso);
  const t = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return t;
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  if (d.toDateString() === tomorrow.toDateString()) return `tomorrow ${t}`;
  return `${d.toLocaleDateString(undefined, { weekday: "short" })} ${t}`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return toDate(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

export function pct(x: number | null | undefined): string {
  return x == null ? "—" : `${Math.round(x * 100)}%`;
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? word : many}`;
}

/** How searches are worded (Search criteria, Scan now). */
export const WORDING_OPTS: { value: QueryWording; label: string }[] = [
  { value: "plain", label: "Plain" },
  { value: "exact", label: "Exact title" },
  { value: "titles", label: "Title group" },
  { value: "titles_keywords", label: "Titles + keyword" },
];
export const WORDING_HINT: Record<QueryWording, string> = {
  plain: "AI Engineer in India: Google matches loosely (it often returns generic fresher jobs).",
  exact: "\"AI Engineer\" in India: the exact title must appear.",
  titles: "(\"AI Engineer\" OR \"Machine Learning Engineer\") in India: the role's search titles from Memory ▾ Role contexts.",
  titles_keywords: "The title group plus the role's first keyword (e.g. Python): narrower, more on-profile.",
};

/** How a job can be applied to, in words (jobs.apply_route). */
export const APPLY_KIND_LABEL: Record<string, string> = {
  form: "Agent can apply",
  direct: "Employer site",
  account: "Account needed",
  aggregator: "Job board",
  platform: "Login platform",
};
const APPLY_NAMES: Record<string, string> = {
  greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", smartrecruiters: "SmartRecruiters", workable: "Workable",
  recruitee: "Recruitee", workday: "Workday", taleo: "Taleo", successfactors: "SuccessFactors", icims: "iCIMS",
  oracle: "Oracle", linkedin: "LinkedIn", naukri: "Naukri", indeed: "Indeed", glassdoor: "Glassdoor",
  internshala: "Internshala", foundit: "foundit", instahyre: "Instahyre", wellfound: "Wellfound", shine: "Shine",
  apna: "apna", hirist: "hirist", cutshort: "Cutshort", iimjobs: "iimjobs", timesjobs: "TimesJobs", jooble: "Jooble",
  "talent.com": "Talent.com", kitjob: "Kit Job", jaabz: "Jaabz", jobrapido: "Jobrapido", simplyhired: "SimplyHired",
  jobleads: "JobLeads", careerjet: "Careerjet", adzuna: "Adzuna", prosple: "Prosple",
};

/** "form:greenhouse" -> { kind: "form", label: "Agent can apply · Greenhouse" }. */
export function applyRoute(route: string | null | undefined): { kind: string; label: string } | null {
  if (!route) return null;
  const [kind, name] = route.split(":");
  const base = APPLY_KIND_LABEL[kind] ?? kind;
  return { kind, label: name ? `${base} · ${APPLY_NAMES[name] ?? name}` : base };
}
