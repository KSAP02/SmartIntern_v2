import type {
  CallExplainOut,
  CountryOption,
  CardCreate,
  JobCard,
  JobDetail,
  JobPatch,
  JobsOut,
  JobsQuery,
  CallJobOut,
  ScanSelection,
  JobDecision,
  OverviewOut,
  ScanOut,
  ScheduleSettings,
  SearchSettings,
  SettingsPatch,
  SettingsSection,
  AdminSettings,
  JSearchAnalyticsOut,
  JSearchTestOut,
  ProviderUsageOut,
  ApiCallOut,
  QueryOut,
  SearchPlanOut,
  AdminSettingsOut,
  SourceOut,
  CardOut,
  CardPatch,
  DeskOut,
  FillPreview,
  FillRequest,
  FillResult,
  MemoryOut,
  ProfileOut,
  RoleContextOut,
  RoleContextPatch,
  RoleMatch,
  Profile,
  ResumeDetail,
  ResumeOut,
  ResumePatch,
  SkillGroup,
  StatusOut,
  UploadResult,
} from "./types";

// Blank (local, Docker): same-origin "/api", proxied by the Node server or Vite.
// Deployed split: VITE_API_BASE_URL = the backend's URL (e.g. https://x.onrender.com), set at build time.
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/$/, "") || "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
  }
}

function detailOf(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((e) => {
          if (e && typeof e === "object") {
            const o = e as { loc?: unknown[]; msg?: string };
            const where = Array.isArray(o.loc) ? o.loc.filter((x) => x !== "body").join(".") : "";
            return where ? `${where}: ${o.msg ?? ""}` : (o.msg ?? "");
          }
          return String(e);
        })
        .join("; ");
    }
  }
  if (status === 502) return "Upstream service error";
  if (status === 503) return "Service not configured";
  return `Request failed (${status})`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "content-type": "application/json" };
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(0, "Can't reach the server. Is it running?");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) throw new ApiError(res.status, detailOf(data, res.status));
  return data as T;
}

export const api = {
  // Records / Vault
  listResumes: () => request<ResumeOut[]>("GET", "/records/vault"),
  getResume: (id: number) => request<ResumeDetail>("GET", `/records/vault/${id}`),
  uploadResumes: (files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return request<UploadResult>("POST", "/records/vault", fd);
  },
  patchResume: (id: number, patch: ResumePatch) => request<ResumeOut>("PATCH", `/records/vault/${id}`, patch),
  reparseResume: (id: number) => request<ResumeOut>("POST", `/records/vault/${id}/reparse`),
  deleteResume: (id: number) => request<void>("DELETE", `/records/vault/${id}`),
  resumeFileUrl: (id: number) => `${API_BASE}/records/vault/${id}/file`,

  // Records / Me
  getProfile: () => request<ProfileOut>("GET", "/records/profile"),
  putProfile: (profile: Profile) => request<ProfileOut>("PUT", "/records/profile", profile),
  previewFill: (req: Omit<FillRequest, "preview">) =>
    request<FillPreview>("POST", "/records/profile/fill", { ...req, preview: true }),
  applyFill: (req: Omit<FillRequest, "preview">) =>
    request<FillResult>("POST", "/records/profile/fill", { ...req, preview: false }),
  confirmProfile: () => request<ProfileOut>("POST", "/records/profile/confirm"),
  /** Proposes themed skill groups; nothing is saved. */
  regroupSkills: (groups: SkillGroup[]) =>
    request<{ groups: SkillGroup[] }>("POST", "/records/profile/skills/regroup", { groups }),

  // Records / Memory
  getMemory: () => request<MemoryOut>("GET", "/records/memory"),
  addCard: (c: CardCreate) => request<CardOut>("POST", "/records/memory", c),
  patchCard: (id: number, p: CardPatch) => request<CardOut>("PATCH", `/records/memory/${id}`, p),
  deleteCard: (id: number) => request<void>("DELETE", `/records/memory/${id}`),
  rebuildMemory: () => request<MemoryOut>("POST", "/records/memory/rebuild"),
  /** Memory ▾ Role contexts (Phase 2.6). */
  listRoleContexts: () => request<RoleContextOut[]>("GET", "/records/memory/roles"),
  ensureRoleContexts: () => request<RoleContextOut[]>("POST", "/records/memory/roles/ensure"),
  patchRoleContext: (id: number, p: RoleContextPatch) => request<RoleContextOut>("PATCH", `/records/memory/roles/${id}`, p),
  regenerateRoleContext: (id: number) => request<RoleContextOut>("POST", `/records/memory/roles/${id}/regenerate`),
  testRoleContexts: (text: string) => request<RoleMatch[]>("POST", "/records/memory/roles/test", { text }),

  // Scout / Search (Job Search)
  searchOverview: () => request<OverviewOut>("GET", "/scout/search/overview"),
  listJobs: (q: JobsQuery = {}) => {
    const p = new URLSearchParams();
    if (q.q) p.set("q", q.q);
    if (q.category) p.set("category", q.category);
    if (q.workplace) p.set("workplace", q.workplace);
    if (q.view && q.view !== "matches") p.set("view", q.view);
    if (q.max_years != null) p.set("max_years", String(q.max_years));
    const qs = p.toString();
    return request<JobsOut>("GET", `/scout/search/jobs${qs ? `?${qs}` : ""}`);
  },
  getJob: (id: number) => request<JobDetail>("GET", `/scout/search/jobs/${id}`),
  patchJob: (id: number, p: JobPatch) => request<JobCard>("PATCH", `/scout/search/jobs/${id}`, p),
  /** Your call on relevance (null = let the checks decide again). */
  setRelevance: (id: number, override: "relevant" | "not_relevant" | null) =>
    request<JobCard>("POST", `/scout/search/jobs/${id}/relevance`, { override }),
  /** The jobs one JSearch request returned, and what became of each. */
  callJobs: (callId: number) => request<CallJobOut[]>("GET", `/scout/search/calls/${callId}/jobs`),
  listPlaces: () => request<CountryOption[]>("GET", "/scout/search/places"),
  callExplain: (callId: number) => request<CallExplainOut>("GET", `/scout/search/calls/${callId}/explain`),
  decideJobs: (ids: number[], decision: JobDecision | null) =>
    request<{ updated: number; decision: JobDecision | null }>("POST", "/scout/search/jobs/decide", { ids, decision }),
  /** Add a job title to Search criteria → Roles you want. */
  addRole: (role: string) => request<SearchSettings>("POST", "/scout/search/roles", { role }),
  /** No selection = the automatic-scan plan; with one = only those roles (one request each, or one OR request). */
  startScan: (selection?: ScanSelection) => request<ScanOut>("POST", "/scout/search/scan", selection),
  /** Dry run: what Scan now would send for this choice. Calls nothing. */
  planScan: (selection: ScanSelection) => request<SearchPlanOut>("POST", "/scout/search/plan", selection),
  listScans: () => request<ScanOut[]>("GET", "/scout/search/scans"),
  setAutoscan: (enabled: boolean) => request<ScheduleSettings>("PUT", "/scout/search/autoscan", { enabled }),
  getSearchSettings: () => request<SearchSettings>("GET", "/scout/search/settings"),
  patchSearchSettings: (p: SettingsPatch) => request<SearchSettings>("PATCH", "/scout/search/settings", p),
  resetSearchSettings: (section: SettingsSection) =>
    request<SearchSettings>("POST", "/scout/search/settings/reset", { section }),
  listSources: () => request<SourceOut[]>("GET", "/scout/search/settings/sources"),
  getSearchPlan: () => request<SearchPlanOut>("GET", "/scout/search/plan"),
  patchQuery: (id: number, enabled: boolean) => request<QueryOut>("PATCH", `/scout/search/queries/${id}`, { enabled }),
  listApiCalls: (limit = 50) => request<ApiCallOut[]>("GET", `/scout/search/calls?limit=${limit}`),

  // Scout / Compass
  remap: () => request<{ remapped: number }>("POST", "/scout/compass/remap"),

  // Insight / System
  desk: () => request<DeskOut>("GET", "/insight/desk"),

  // Admin / JSearch analytics
  getJSearchAnalytics: (days = 30) => request<JSearchAnalyticsOut>("GET", `/system/jsearch?days=${days}`),
  refreshJSearchUsage: () => request<ProviderUsageOut>("POST", "/system/jsearch/usage"),
  testJSearch: () => request<JSearchTestOut>("POST", "/system/jsearch/test"),

  // System / Admin settings (settings/config.toml)
  getAdminSettings: () => request<AdminSettingsOut>("GET", "/system/admin"),
  saveAdminSettings: (settings: AdminSettings, version: string) =>
    request<AdminSettingsOut>("PUT", "/system/admin", { settings, version }),
  status: () => request<StatusOut>("GET", "/system/status"),
};

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.detail;
  if (e instanceof Error) return e.message;
  return String(e);
}
