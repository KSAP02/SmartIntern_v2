import { useEffect, useState } from "react";
import type { ComponentType } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { BarChart3, Brain, Building2, ChevronDown, ChevronRight, FileCog, FileStack, LayoutDashboard, Menu, Moon, Radar, SlidersHorizontal, Sun, UserRound, X } from "lucide-react";
import { api } from "./lib/api";
import { cx } from "./lib/util";
import { PROFILE_EVENT } from "./components/ProfileBar";
import Desk from "./pages/Desk";
import Vault from "./pages/Vault";
import Profile from "./pages/Profile";
import Memory from "./pages/Memory";
import RoleContexts from "./pages/RoleContexts";
import Switchboard from "./pages/Switchboard";
import JobSearchOverview from "./pages/JobSearchOverview";
import JobSearchJobs from "./pages/JobSearchJobs";
import JobSearchSettings from "./pages/JobSearchSettings";
import AdminSettings from "./pages/AdminSettings";
import JSearchAnalytics from "./pages/JSearchAnalytics";
import CompanyFinderAnalytics from "./pages/CompanyFinderAnalytics";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string; strokeWidth?: number }>;
  /** An expandable group: clicking the parent toggles it; it opens on any child path. */
  children?: { to: string; label: string }[];
}
// Only rooms that exist today; later rooms (Applications...) appear when they're built.
const NAV: { wing: string; items: NavItem[] }[] = [
  { wing: "Insight", items: [{ to: "/", label: "Desk", icon: LayoutDashboard }] },
  {
    wing: "Records",
    items: [
      { to: "/vault", label: "Vault", icon: FileStack },
      { to: "/profile", label: "My Profile", icon: UserRound },
      {
        to: "/memory",
        label: "Memory",
        icon: Brain,
        children: [
          { to: "/memory", label: "Cards" },
          { to: "/memory/roles", label: "Role contexts" },
        ],
      },
    ],
  },
  {
    wing: "Utility",
    items: [
      {
        to: "/job-search",
        label: "Job Search",
        icon: Radar,
        children: [
          { to: "/job-search", label: "Scan Jobs" },
          { to: "/job-search/jobs", label: "Jobs" },
          { to: "/job-search/settings", label: "Search Settings" },
        ],
      },
    ],
  },
  {
    wing: "Admin",
    items: [
      { to: "/admin", label: "Admin settings", icon: FileCog },
      { to: "/jsearch", label: "JSearch analytics", icon: BarChart3 },
      { to: "/company-finder", label: "Company finder", icon: Building2 },
      { to: "/switchboard", label: "Switchboard", icon: SlidersHorizontal },
    ],
  },
];

const linkBase = "relative flex items-center gap-3 px-3 py-1.5 text-sm transition-colors duration-150";
const linkActive =
  "text-zinc-900 before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-violet-600 dark:text-zinc-50 dark:before:bg-violet-400";
const linkIdle = "text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100";
const navLinkClass = ({ isActive }: { isActive: boolean }) => cx(linkBase, isActive ? linkActive : linkIdle);

function readCollapsed(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem("nav-collapsed") ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** Expandable sidebar entry. Auto-opens on its pages unless the user collapsed it (remembered). */
function NavGroup({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const inside = pathname === item.to || pathname.startsWith(item.to + "/");
  const [collapsed, setCollapsed] = useState(() => readCollapsed().includes(item.to));
  const [opened, setOpened] = useState(false);
  const open = opened || (inside && !collapsed);

  const toggle = () => {
    const next = !open;
    setOpened(next);
    setCollapsed(!next);
    try {
      const rest = readCollapsed().filter((x) => x !== item.to);
      localStorage.setItem("nav-collapsed", JSON.stringify(next ? rest : [...rest, item.to]));
    } catch {}
  };
  const id = `nav-${item.to.replace(/\W+/g, "-")}`;

  return (
    <div>
      <button type="button" onClick={toggle} aria-expanded={open} aria-controls={id} className={cx(linkBase, "w-full", inside ? "text-zinc-900 dark:text-zinc-50" : linkIdle)}>
        <item.icon className="size-4" strokeWidth={1.75} />
        <span className="flex-1 text-left">{item.label}</span>
        {open ? <ChevronDown className="size-3.5 text-zinc-400" /> : <ChevronRight className="size-3.5 text-zinc-400" />}
      </button>
      {open && (
        <div id={id} className="flex flex-col">
          {item.children!.map((c) => (
            <NavLink key={c.to} to={c.to} end onClick={onNavigate} className={(s) => cx(navLinkClass(s), "pl-10")}>
              {c.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  const toggle = () => {
    setDark((d) => {
      try {
        localStorage.setItem("theme", d ? "light" : "dark");
      } catch {}
      return !d;
    });
  };
  return { dark, toggle };
}

function useSystemHealth() {
  const [state, setState] = useState<"ok" | "warn" | "down" | "unknown">("unknown");
  const [detail, setDetail] = useState("Checking…");
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const s = await api.status();
        if (!alive) return;
        const bad = Object.entries(s.components).filter(([, c]) => !c.ok);
        setState(bad.length ? "warn" : "ok");
        setDetail(bad.length ? `Needs attention: ${bad.map(([k]) => k).join(", ")}` : "All systems ready");
      } catch {
        if (!alive) return;
        setState("down");
        setDetail("Backend unreachable");
      }
    };
    void check();
    const t = window.setInterval(check, 30000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);
  return { state, detail };
}

function Logo() {
  return (
    <span className="font-serif text-xl tracking-tight text-zinc-900 dark:text-zinc-50">
      SmartIntern<span className="text-violet-600 dark:text-violet-400">.</span>
    </span>
  );
}

/** The active profile's name (Phase 2.8); reloads after a switch. */
function ActiveProfile({ onNavigate }: { onNavigate?: () => void }) {
  const [name, setName] = useState<string | null>(null);
  const [count, setCount] = useState(0);
  useEffect(() => {
    const load = () =>
      api.listProfiles().then(
        (d) => {
          setName(d.profiles.find((p) => p.active)?.name ?? null);
          setCount(d.profiles.length);
        },
        () => setName(null),
      );
    void load();
    window.addEventListener(PROFILE_EVENT, load);
    return () => window.removeEventListener(PROFILE_EVENT, load);
  }, []);
  if (!name) return null;
  return (
    <NavLink
      to="/profile"
      onClick={onNavigate}
      title={count > 1 ? "Active profile: switch on My Profile" : "Your profile"}
      className="mb-6 flex items-center gap-2 truncate px-3 text-xs text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
    >
      <UserRound className="size-3.5 shrink-0" strokeWidth={1.75} />
      <span className="truncate">{name}</span>
    </NavLink>
  );
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-6">
      {NAV.map((g) => (
        <div key={g.wing}>
          <p className="mb-2 px-3 text-[11px] text-zinc-400 dark:text-zinc-500">{g.wing}</p>
          <div className="flex flex-col">
            {g.items.map((it) =>
              it.children ? (
                <NavGroup key={it.label} item={it} onNavigate={onNavigate} />
              ) : (
                <NavLink key={it.label} to={it.to} end={it.to === "/"} onClick={onNavigate} className={navLinkClass}>
                  <it.icon className="size-4" strokeWidth={1.75} />
                  {it.label}
                </NavLink>
              ),
            )}
          </div>
        </div>
      ))}
    </nav>
  );
}

function Footer({ dark, toggle }: { dark: boolean; toggle: () => void }) {
  const health = useSystemHealth();
  const dot = { ok: "bg-emerald-500", warn: "bg-amber-500", down: "bg-rose-500", unknown: "bg-zinc-400" }[health.state];
  return (
    <div className="flex items-center justify-between gap-2 border-t border-zinc-200 pt-4 dark:border-zinc-800">
      <NavLink to="/switchboard" className="flex min-w-0 items-center gap-2 px-3 py-1 text-xs text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200">
        <span className={cx("inline-flex size-1.5 shrink-0 rounded-full", dot)} />
        <span className="truncate">{health.detail}</span>
      </NavLink>
      <button
        onClick={toggle}
        aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
        title={dark ? "Light mode" : "Dark mode"}
        className="rounded-md p-1.5 text-zinc-400 transition-colors hover:text-zinc-900 dark:text-zinc-500 dark:hover:text-zinc-100"
      >
        {dark ? <Sun className="size-4" strokeWidth={1.75} /> : <Moon className="size-4" strokeWidth={1.75} />}
      </button>
    </div>
  );
}

export default function App() {
  const { dark, toggle } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setMenuOpen(false), [location.pathname]);

  return (
    <div className="min-h-screen">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-56 flex-col border-r border-zinc-200 bg-zinc-50 px-3 py-7 lg:flex dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mb-4 px-3">
          <Logo />
        </div>
        <ActiveProfile />
        <div className="flex-1 overflow-y-auto">
          <Nav />
        </div>
        <Footer dark={dark} toggle={toggle} />
      </aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-zinc-200 bg-zinc-50 px-4 py-3 lg:hidden dark:border-zinc-800 dark:bg-zinc-950">
        <Logo />
        <button
          onClick={() => setMenuOpen((o) => !o)}
          aria-label="Menu"
          className="rounded-md p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-900"
        >
          {menuOpen ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </header>
      {menuOpen && (
        <div className="fade-in fixed inset-x-0 top-[57px] bottom-0 z-20 overflow-y-auto bg-zinc-50 px-4 py-5 lg:hidden dark:bg-zinc-950">
          <ActiveProfile onNavigate={() => setMenuOpen(false)} />
          <Nav onNavigate={() => setMenuOpen(false)} />
          <div className="mt-6">
            <Footer dark={dark} toggle={toggle} />
          </div>
        </div>
      )}

      <main className="lg:pl-56">
        <div key={location.pathname} className="page-in mx-auto max-w-[1040px] px-4 py-8 sm:px-10 lg:py-14">
          <Routes>
            <Route path="/" element={<Desk />} />
            <Route path="/desk" element={<Desk />} />
            <Route path="/vault" element={<Vault />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/me" element={<Navigate to="/profile" replace />} />
            <Route path="/memory" element={<Memory />} />
            <Route path="/memory/roles" element={<RoleContexts />} />
            <Route path="/job-search" element={<JobSearchOverview />} />
            <Route path="/job-search/jobs" element={<JobSearchJobs />} />
            <Route path="/job-search/settings" element={<JobSearchSettings />} />
            <Route path="/switchboard" element={<Switchboard />} />
            <Route path="/admin" element={<AdminSettings />} />
            <Route path="/jsearch" element={<JSearchAnalytics />} />
            <Route path="/company-finder" element={<CompanyFinderAnalytics />} />
            <Route
              path="*"
              element={
                <div className="py-24 text-center">
                  <p className="text-sm text-zinc-500">This room doesn't exist yet.</p>
                  <NavLink to="/" className="mt-3 inline-block text-sm font-medium text-violet-600 hover:underline">
                    Back to your desk
                  </NavLink>
                </div>
              }
            />
          </Routes>
        </div>
      </main>
    </div>
  );
}
