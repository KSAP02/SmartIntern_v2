import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "./api";
import type { Profile } from "./types";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function newId(): string {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z").getTime();
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d} d ago`;
  return new Date(t).toLocaleDateString();
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
  return t.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export function emptyProfile(): Profile {
  return {
    personal: {
      full_name: null,
      email: null,
      phone: null,
      address: { line1: null, line2: null, city: null, state: null, postal_code: null, country: null },
      links: { linkedin: null, github: null, portfolio: null, other: [] },
    },
    headline: { current_title: null, summary: null, years_experience: null },
    skills: { groups: [], languages: [] },
    work_history: [],
    education: [],
    projects: [],
    certifications: [],
    preferences: {
      roles_of_interest: [],
      preferred_locations: [],
      remote_preference: null,
      employment_types: [],
      minimum_salary: null,
      salary_currency: null,
      notice_period: null,
      work_authorization: null,
      earliest_start_date: null,
    },
  };
}

/** Load data once, expose reload, and optionally keep polling while `shouldPoll(data)` is true. */
export function useResource<T>(
  load: () => Promise<T>,
  opts: { pollMs?: number; shouldPoll?: (d: T) => boolean } = {},
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  loadRef.current = load;
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const reload = useCallback(async () => {
    try {
      const d = await loadRef.current();
      setData(d);
      setError(null);
      return d;
    } catch (e) {
      setError(errorMessage(e));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    const { pollMs = 2000, shouldPoll } = optsRef.current;
    if (!shouldPoll || data === null || !shouldPoll(data)) return;
    const t = window.setTimeout(() => void reload(), pollMs);
    return () => window.clearTimeout(t);
  }, [data, reload]);

  return { data, setData, error, loading, reload };
}
