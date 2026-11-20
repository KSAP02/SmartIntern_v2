// Mirrors backend/schemas.py. Keep the two in sync.

export interface Address {
  line1: string | null;
  line2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  country: string | null;
}

export interface Links {
  linkedin: string | null;
  github: string | null;
  portfolio: string | null;
  other: string[];
}

export interface Personal {
  full_name: string | null;
  email: string | null;
  phone: string | null;
  address: Address;
  links: Links;
}

export interface Headline {
  current_title: string | null;
  summary: string | null;
  years_experience: number | null;
}

export interface SkillGroup {
  id: string;
  name: string | null;
  items: string[];
}

export interface Skills {
  /** Themed groups ("Backend & APIs", ...). Each group becomes one memory card. */
  groups: SkillGroup[];
  /** Spoken languages. */
  languages: string[];
}

export interface WorkItem {
  id: string;
  company: string | null;
  title: string | null;
  location: string | null;
  start: string | null;
  end: string | null;
  is_current: boolean;
  bullets: string[];
}

export interface EducationItem {
  id: string;
  institution: string | null;
  degree: string | null;
  field: string | null;
  start: string | null;
  end: string | null;
  grade: string | null;
}

export interface ProjectItem {
  id: string;
  name: string | null;
  description: string | null;
  tech: string[];
  url: string | null;
}

export interface CertificationItem {
  id: string;
  name: string | null;
  issuer: string | null;
  date: string | null;
}

export type RemotePreference = "any" | "remote" | "hybrid" | "onsite";

export interface Preferences {
  roles_of_interest: string[];
  preferred_locations: string[];
  remote_preference: RemotePreference | null;
  employment_types: string[];
  minimum_salary: number | null;
  salary_currency: string | null;
  notice_period: string | null;
  work_authorization: string | null;
  earliest_start_date: string | null;
}

export interface Profile {
  personal: Personal;
  headline: Headline;
  skills: Skills;
  work_history: WorkItem[];
  education: EducationItem[];
  projects: ProjectItem[];
  certifications: CertificationItem[];
  preferences: Preferences;
}

export interface ProfileOut {
  profile: Profile;
  field_origins: Record<string, string>;
  resume_labels: Record<string, string>;
  last_filled_from_resume_id: number | null;
  confirmed_at: string | null;
  updated_at: string | null;
  completeness: number;
  memory_stale: boolean;
}

export type FillMode = "empty_only" | "replace";

export interface FillRequest {
  resume_id: number;
  mode: FillMode;
  preview: boolean;
  exclude_fields: string[];
}

export interface FillChange {
  path: string;
  section: string;
  label: string;
  action: "set" | "add" | "update";
  current: unknown;
  incoming: unknown;
  user_edited: boolean;
}

export interface FillPreview {
  resume_id: number;
  resume_label: string;
  mode: FillMode;
  changes: FillChange[];
}

export interface FillResult {
  applied: number;
  view: ProfileOut;
}

export type ParseStatus = "pending" | "parsing" | "parsed" | "failed";

export interface ResumeOut {
  id: number;
  label: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  parse_status: ParseStatus;
  parse_error: string | null;
  is_default: boolean;
  has_parsed_data: boolean;
  created_at: string;
  updated_at: string;
}

export interface ResumeDetail extends ResumeOut {
  extracted_text: string | null;
  parsed_data: Profile | null;
}

export interface UploadError {
  filename: string;
  detail: string;
}

export interface UploadResult {
  items: ResumeOut[];
  duplicates: number[];
  errors: UploadError[];
}

export interface ResumePatch {
  label?: string;
  is_default?: boolean;
}

export type CardKind = "summary" | "experience" | "project" | "education" | "skills" | "certification" | "custom";

export interface CardOut {
  id: number;
  kind: CardKind;
  title: string;
  text: string;
  enabled: boolean;
  pinned: boolean;
  origin: "generated" | "user";
  user_edited: boolean;
  source_ref: string | null;
  position: number;
  updated_at: string;
}

export interface MemoryOut {
  cards: CardOut[];
  built_at: string | null;
  memory_stale: boolean;
}

export interface CardCreate {
  title: string;
  text: string;
}

export interface CardPatch {
  title?: string;
  text?: string;
  enabled?: boolean;
  pinned?: boolean;
}

/** Phase 2.6: one job-description-style context per role (Memory ▾ Role contexts). */
export interface RoleRef {
  id: number | null;
  label: string;
}

export interface RoleContextOut {
  /** null = not written yet (status "missing"). */
  id: number | null;
  role: string;
  status: "missing" | "pending" | "ready" | "failed";
  error?: string | null;
  summary: string;
  responsibilities: string[];
  requirements: string[];
  nice_to_have: string[];
  /** Used to word searches (not embedded). */
  search_titles: string[];
  keywords: string[];
  /** Exactly what is embedded and compared with jobs. */
  text: string;
  edited: boolean;
  generated_at: string | null;
  updated_at: string | null;
  model: string | null;
  cards: RoleRef[];
  example_jobs: RoleRef[];
  memory_changed: boolean;
  in_roles: boolean;
}

export type RoleContextPatch = Partial<Pick<RoleContextOut, "summary" | "responsibilities" | "requirements" | "nice_to_have" | "search_titles" | "keywords">>;

export interface RoleMatch {
  role: string;
  context_id: number | null;
  score: number;
}

export interface ComponentStatus {
  ok: boolean;
  detail: string;
}

export interface DeskOut {
  first_name: string | null;
  completeness: number;
  profile_confirmed: boolean;
  resumes: Record<string, number>;
  cards: Record<string, number>;
  memory_stale: boolean;
  status: Record<string, ComponentStatus>;
  /** found_today, relevant, fits_preset (numbers); last_scan_at, next_scan_at (ISO or null). */
  job_search?: {
    found_today?: number;
    relevant?: number;
    fits_preset?: number;
    last_scan_at?: string | null;
    next_scan_at?: string | null;
  };
}

export interface StatusOut {
  app: string;
  config_file: string;
  config_loaded: boolean;
  llm: Record<string, unknown>;
  embedding: Record<string, unknown>;
  limits: Record<string, unknown>;
  components: Record<string, ComponentStatus>;
}

// ── Job Search (Phase 2) — mirrors backend/job_schemas.py ──────────────────────

export type Category = "internship" | "full_time" | "part_time" | "contract" | "freelance";
export type Workplace = "remote" | "hybrid" | "onsite";
export type Compensation = "paid" | "stipend" | "unpaid";
export type Seniority = "intern" | "entry" | "mid" | "senior" | "lead";
export type SalaryPeriod = "year" | "month" | "week" | "day" | "hour";
export type FactSource = "source" | "rules" | "ai";

/** Before gathering. "All" is always the empty list / null. */
export interface SearchCriteria {
  /** "Roles you want": when set, a job is relevant only if its title matches one. */
  roles: string[];
  /** Automatic scans: which roles ([] = all) ... */
  auto_roles: string[];
  /** ... and how: rotate (one role per request, taking turns), each (one request per role every scan), combined (all in one OR request). */
  auto_mode: "rotate" | "each" | "combined";
  job_types: Category[];
  workplace: Workplace[];
  locations: string[];
  /** With locations set: keep jobs whose location can't be read. */
  keep_unknown_location: boolean;
  /** Sent to JSearch (job_requirements) and checked against the years a job asks for. */
  /** Your years of experience: jobs asking for more are dropped; 0-2 also ask JSearch for entry level. null = any. */
  experience_years: number | null;
  posted_within_days: number | null;
  /** How searches are worded (the JSearch adapter writes the syntax). */
  query_wording: QueryWording;
  exclude_title_words: string[];
  exclude_companies: string[];
}

/** Before applying: sorts gathered jobs into "Fits your preset" / "Other relevant". */
export interface ApplyPreset {
  pay: Compensation[];
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  salary_period: SalaryPeriod;
  min_fit: number | null;
  seniority: Seniority[];
  max_years_experience: number | null;
  needs_visa_sponsorship: boolean;
  max_internship_months: number | null;
  only_companies: string[];
  include_unknown: boolean;
}

/** JSearch, the only job source (config.toml [scout.search.sources]; Admin settings → JSearch). */
export interface SourcesSettings {
  enabled: boolean;
  /** Where JSEARCH_API_KEY is from: OpenWeb Ninja directly (also gives plan usage) or RapidAPI. */
  provider: "openwebninja" | "rapidapi";
  /** Hard cap of requests per billing period (free plan: 200). One request = up to 10 jobs. */
  monthly_limit: number;
  /** Limit requests per day: on = at most daily_limit a day from today; off = use what's left. */
  daily_limit_on: boolean;
  daily_limit: number;
  /** Kept back from scans for calibration / manual tests. */
  reserve: number;
  max_per_scan: number;
  pages_policy: "single" | "smart";
  page2_min_new: number;
  backoff_after_empty: number;
  timeout_seconds: number;
  api_country: string;
  excluded_publishers: string[];
  /** A repeat search never asks for a narrower posting window than this. */
  min_date_posted: "today" | "3days" | "week" | "month" | "all";
  /** Send your years of experience to JSearch (job_requirements). */
  send_experience_filter: boolean;
}

export type QueryWording = "plain" | "exact" | "titles" | "titles_keywords";

export interface ScheduleSettings {
  autoscan: boolean;
  time: string;
  every_hours: 12 | 24;
  recency_days: number;
  /** IANA zone the daily time is in, e.g. "Asia/Kolkata". */
  timezone: string;
}

/** Jobs stay until you discard them (or the agent applies); only discarded jobs are deleted. */
export interface LimitsSettings {
  keep_discarded_days: number;
  /** Posted (or found) longer ago → labelled "expired" (nothing is deleted for age). */
  expire_after_days: number;
  raw_payload_days: number;
  repost_window_days: number;
}

export interface MatchingSettings {
  metric: "COSINE" | "IP" | "L2";
  role_threshold: number;
  /** A title at least this close still counts when the job text matches that role's context. 0 = off. */
  borderline_role_threshold: number;
  borderline_context_threshold: number;
}

export interface SearchSettings {
  criteria: SearchCriteria;
  preset: ApplyPreset;
  sources: SourcesSettings;
  schedule: ScheduleSettings;
  limits: LimitsSettings;
  matching: MatchingSettings;
}

/** Saved from Search Settings. The other sections live in config.toml (Admin settings). */
export type SettingsSection = "criteria" | "preset";

/** criteria and/or preset; each given section is replaced as a whole. */
export type SettingsPatch = Partial<Pick<SearchSettings, SettingsSection>>;

// ── Admin settings (System → Admin settings = settings/config.toml) ──────────

export interface LLMParams {
  provider: string;
  model: string;
  temperature: number | null;
  reasoning_effort: string | null;
  max_output_tokens: number;
  timeout_seconds: number;
  max_retries: number;
}

/** [llm.tasks.<task>]: null = inherit from the LLM defaults. */
export interface LLMTaskOverride {
  temperature: number | null;
  reasoning_effort: string | null;
  max_output_tokens: number | null;
}

export interface EmbeddingSettings {
  provider: string;
  model: string;
  dimensions: number;
  batch_size: number;
}

export interface ModelsSettings {
  llm: LLMParams;
  tasks: Record<string, LLMTaskOverride>;
  embedding: EmbeddingSettings;
}

export interface AdminSettings {
  models: ModelsSettings;
  matching: MatchingSettings;
  sources: SourcesSettings;
  schedule: ScheduleSettings;
  limits: LimitsSettings;
}

export type AdminSection = keyof AdminSettings;

export interface AdminSettingsOut {
  settings: AdminSettings;
  /** Changes whenever config.toml changes; send it back when saving. */
  version: string;
  file: string;
  file_error: string | null;
  section_errors: Record<string, string>;
  /** config.toml keys overridden by .env, e.g. "llm.model" → value. */
  env_overrides: Record<string, string>;
}

export interface SourceOut {
  name: string;
  label: string;
  kind: "feed" | "ats";
  enabled: boolean;
  terms_url: string | null;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error: string | null;
  active_jobs: number;
  /** False = needs API keys in .env (see setup_hint). */
  configured: boolean;
  setup_hint: string | null;
}

export interface FetchRunOut {
  source: string;
  company: string | null;
  status: "running" | "ok" | "failed";
  fetched: number;
  new: number;
  updated: number;
  duplicates: number;
  already_seen: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export type ScanPhase = "fetching" | "processing" | "mapping" | "pruning" | "done" | "failed";

export interface ScanOut {
  scan_id: string;
  trigger: "manual" | "auto";
  phase: ScanPhase;
  started_at: string;
  finished_at: string | null;
  /** fetched, new, updated, duplicates, already_seen, excluded, not_relevant, relevant, mapped */
  totals: Record<string, number>;
  runs: FetchRunOut[];
  error: string | null;
}

export interface DayCount {
  date: string;
  source: string;
  found: number;
  new: number;
}

export interface OverviewOut {
  running: ScanOut | null;
  last_scan: ScanOut | null;
  autoscan: boolean;
  next_scan_at: string | null;
  per_day: DayCount[];
  /** seen, excluded, not_relevant, relevant, mapped, fits_preset */
  funnel: Record<string, number>;
  /** category / workplace / country -> value -> count */
  breakdown: Record<string, Record<string, number>>;
  sources: SourceOut[];
  quota: QuotaOut | null;
  memory_ready: boolean;
}

export interface Coverage {
  must_total: number;
  must_met: number;
  must_partial: number;
  must_missing: number;
  nice_total: number;
  nice_met: number;
  fit: number | null;
}

export interface SeenOn {
  source: string;
  job_url: string | null;
}

export interface JobCard {
  id: number;
  title: string;
  company_name: string | null;
  location_text: string | null;
  category: Category | null;
  workplace_type: Workplace | null;
  country_codes: string[];
  remote_regions: string[];
  compensation_type: Compensation | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period: string | null;
  seniority: Seniority | null;
  first_seen_at: string;
  source_published_at: string | null;
  seen_on: SeenOn[];
  /** Job text vs the context of role_match (0–1). */
  relevance: number | null;
  role_score: number | null;
  role_match: string | null;
  coverage: Coverage | null;
  pipeline_status: string;
  status_reason: string | null;
  /** Your call: selected (for the agent to apply), discarded, applied; null = undecided. */
  decision: JobDecision | null;
  decided_at: string | null;
  /** Your call on relevance; beats the title check and your criteria. */
  relevance_override: "relevant" | "not_relevant" | null;
  /** Years the posting asks for (null: not stated). */
  min_years_experience: number | null;
  /** The place searched by the request that found it (e.g. "Karnataka, India"). */
  searched_place: string | null;
  /** Is the job there? Never excludes; shown on the row. */
  place_check: "match" | "elsewhere" | "remote" | "unknown" | null;
  /** Posted (or found) longer ago than Limits → expire after. Label only. */
  expired: boolean;
  fits_preset: boolean;
  preset_misses: string[];
  job_url: string | null;
  apply_url: string | null;
}

export type JobDecision = "selected" | "discarded" | "applied";
export type JobsView = "matches" | "selected" | "applied" | "discarded" | "not_relevant" | "excluded";

export interface JobsOut {
  view: JobsView;
  /** view "matches": undecided relevant jobs that fit the apply preset */
  fits: JobCard[];
  /** view "matches": undecided relevant jobs outside the preset */
  other: JobCard[];
  /** every other view */
  items: JobCard[];
  /** fits, other, selected, applied, discarded, not_relevant, excluded */
  counts: Record<string, number>;
}

export interface CardRef {
  card_id: number;
  title: string;
  score: number;
}

export interface RequirementOut {
  id: number;
  section: string;
  importance: "must" | "nice" | "unknown";
  text: string;
  skills: string[];
  status: "met" | "partial" | "missing" | "unknown" | null;
  method: string | null;
  best: CardRef | null;
  evidence: CardRef[];
}

export interface JobDetail extends JobCard {
  description_text: string;
  /** The source gives only a short excerpt, so the evidence map is thin. */
  snippet_only: boolean;
  field_sources: Record<string, FactSource>;
  min_years_experience: number | null;
  internship_duration: string | null;
  visa_sponsorship: "yes" | "no" | null;
  start_date: string | null;
  apply_deadline: string | null;
  tags: string[];
  requirements: RequirementOut[];
  missing_skills: string[];
  matched_skills: string[];
}

export interface JobPatch {
  /** null = back to undecided */
  decision: JobDecision | null;
}

export interface JobsQuery {
  q?: string;
  category?: Category;
  workplace?: Workplace;
  view?: JobsView;
  /** Matches only: hide jobs asking for more years than this (jobs that don't say stay). */
  max_years?: number;
}

// ── JSearch search plan + request budget (Phase 2.5) ─────────────────────────

export interface QuotaOut {
  month_used: number;
  monthly_limit: number;
  reserve: number;
  today_used: number;
  /** What scans may still spend today. */
  today_allowance: number;
  /** What the next scan may spend (today's allowance capped by max per scan). */
  scan_allowance: number;
  resets_on: string;
  blocked_until: string | null;
  /** OpenWeb Ninja's remaining quota minus our requests since it answered; null if unknown. */
  provider_remaining: number | null;
  daily_limit: number;
  daily_limit_on: boolean;
  max_per_scan: number;
  /** Days left in the billing period, today included. */
  days_left: number;
  /** monthly_limit - reserve, and scan requests used / left of it this period. */
  scan_budget: number;
  scan_used: number;
  scan_left: number;
  /** What's left spread evenly over the days left: a fair per-day number now. */
  even_pace: number;
  /** What an even pace from the period start would have used by end of today. */
  expected_by_today: number;
  /** scan_used - expected_by_today: > 0 spent faster than even, < 0 slower. */
  ahead_by: number;
}

/** Admin → JSearch → Test with 1 request. */
export interface JSearchTestOut {
  ok: boolean;
  error: string | null;
  query: string | null;
  params: Record<string, string | number>;
  results: number;
  new_jobs: number;
  relevant_jobs: number;
  shape: string | null;
  countries: Record<string, number>;
  publishers: Record<string, number>;
  types: Record<string, number>;
  has_currency: number;
  has_highlights: number;
  titles: string[];
  fields_seen: string[];
  saved_as: string | null;
}

/** OpenWeb Ninja /usage as last fetched. Fields picked by name; raw has everything. */
export interface ProviderUsageOut {
  fetched_at: string | null;
  error: string | null;
  plan: string | null;
  period_start: string | null;
  period_end: string | null;
  limit: number | null;
  used: number | null;
  remaining: number | null;
  raw: [string, string | number | boolean | null][];
}

export interface UsageDay {
  date: string;
  requests: number;
  errors: number;
  results: number;
  new_jobs: number;
  relevant_jobs: number;
}

export interface JSearchAnalyticsOut {
  configured: boolean;
  provider: string;
  quota: QuotaOut;
  usage: ProviderUsageOut;
  per_day: UsageDay[];
  totals: Record<"requests" | "ok" | "errors" | "scan" | "calibration" | "results" | "new_jobs" | "relevant_jobs", number>;
  per_request: Record<"results" | "new_jobs" | "relevant_jobs", number | null>;
  queries: QueryOut[];
  recent: ApiCallOut[];
  /** Phase 2.6 query lab: what each wording bought. */
  by_wording: WordingYield[];
}

export interface WordingYield {
  variant: string;
  requests: number;
  results: number;
  new_jobs: number;
  relevant_jobs: number;
  relevant_per_request: number | null;
}

export interface PlannedCall {
  query_id: number;
  query: string;
  page: number;
  params: Record<string, string | number>;
  reason: string;
  /** The text your settings generate; custom = you typed another. */
  default_query: string;
  custom: boolean;
  /** Parameter -> where its value came from. */
  sources: Record<string, string>;
  /** Each parameter in plain words. */
  explain: ParamNote[];
  /** The same search before (newest first). */
  history: PastRequest[];
}

/** One sent parameter: what JSearch / Google for Jobs does with it. */
export interface ParamNote {
  key: string;
  value: string;
  meaning: string;
  /** It removes postings Google would otherwise return. */
  narrows: boolean;
  /** Often the reason for few or off-target results. */
  warn: boolean;
  /** Where the value came from (your settings); empty for past requests. */
  source: string;
}

/** An earlier request for the same search and how it went. */
export interface PastRequest {
  id: number;
  at: string;
  query: string;
  results: number;
  relevant: number;
  variant: string | null;
  /** What it sent differently, e.g. "date_posted: month". */
  differs: string[];
}

/** Why one past request returned what it did. */
export interface CallExplainOut {
  params: ParamNote[];
  findings: string[];
  suggestions: string[];
  history: PastRequest[];
}

export interface QueryOut {
  id: number;
  role: string;
  place: string;
  country: string;
  query: string;
  /** Combined (OR) search: its roles; [] = one role. */
  roles: string[];
  active: boolean;
  enabled: boolean;
  interval_days: number;
  last_run_at: string | null;
  next_due_at: string | null;
  runs: number;
  results: number;
  new_jobs: number;
  relevant_jobs: number;
  /** Relevant new jobs per request over recent runs; null before the first run. */
  yield_per_request: number | null;
  zero_streak: number;
}

/** Scan now with your choice of roles. */
export interface ScanSelection {
  roles: string[];
  /** true = one request "A OR B in <place>" instead of one per role */
  combine: boolean;
  /** This scan only; left out = your Search criteria. */
  locations?: string[];
  job_types?: Category[];
  workplace?: Workplace[];
  /** Sent (even null = any) -> replaces your criteria's years for this scan. */
  experience_years?: number | null;
  wording?: QueryWording;
  /** Send the experience filter to JSearch this time (default: Admin settings). */
  send_experience?: boolean;
  /** date_posted for this scan; left out = automatic (since this search last ran, at least the floor). */
  date_posted?: DatePosted;
  /** Query text you typed, per search (query_id -> text); left out = the generated text. */
  query_texts?: Record<number, string>;
}

/** A country for the location picker, with the states / cities we know there. */
export interface CountryOption {
  code: string;
  name: string;
  places: string[];
}

export type DatePosted = "today" | "3days" | "week" | "month" | "all";

export interface SearchPlanOut {
  configured: boolean;
  enabled: boolean;
  kind: "auto" | "manual";
  mode: "rotate" | "each" | "combined" | "separate";
  /** Requests this scan may spend (auto: per-scan cap; manual: what's left today). */
  allowance: number;
  /** Manual: false when the choice needs more requests than allowed now. */
  fits_budget: boolean;
  calls: PlannedCall[];
  queries: QueryOut[];
  quota: QuotaOut;
  notes: string[];
  /** The wording of these requests, e.g. "titles · exp off". */
  variant: string | null;
  /** What we check on the jobs that come back, in plain words. */
  after: string[];
  /** Your settings that aren't sent to JSearch, and why. */
  not_sent: string[];
}

/** One job a request returned, and what became of it. */
export interface CallJobOut {
  position: number;
  title: string;
  company_name: string | null;
  location_text: string | null;
  outcome: "new" | "updated" | "unchanged" | "duplicate" | "already_seen" | "too_old";
  job_id: number | null;
  pipeline_status: string | null;
  status_reason: string | null;
  decision: JobDecision | null;
  role_score: number | null;
  role_match: string | null;
}

export interface ApiCallOut {
  id: number;
  at: string;
  query: string | null;
  purpose: string;
  page: number;
  params: Record<string, string | number>;
  status: "sending" | "ok" | "error";
  http_status: number | null;
  results: number;
  new_jobs: number;
  relevant_jobs: number;
  error: string | null;
  variant: string | null;
}
