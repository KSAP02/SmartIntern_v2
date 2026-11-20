import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import {
  ArrowRight,
  Brain,
  CheckCircle2,
  CircleAlert,
  FileStack,
  FileUp,
  Radar,
  Search,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { api } from "../lib/api";
import { cx, greeting, timeAgo, useResource } from "../lib/util";
import { Button, Card, ErrorBanner, Skeleton } from "../components/ui";
import { ProgressRing } from "../components/ProgressRing";

const COMPONENT_LABELS: Record<string, string> = {
  llm: "Language model",
  embeddings: "Embeddings",
  vectors: "Vector store",
  database: "Database",
  storage: "File storage",
};

function Tile({
  icon,
  label,
  value,
  hint,
  to,
  muted,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  to?: string;
  muted?: boolean;
}) {
  const body = (
    <Card
      className={cx(
        "h-full p-5 transition-all duration-150",
        to && "hover:border-zinc-400 dark:hover:border-zinc-600",
        muted && "bg-zinc-50/60 dark:bg-zinc-900/40",
      )}
    >
      <div className={cx("flex items-center gap-2 text-xs font-medium", muted ? "text-zinc-400 dark:text-zinc-600" : "text-zinc-500 dark:text-zinc-400")}>
        {icon}
        {label}
      </div>
      <div className={cx("mt-3 text-2xl font-semibold tabular-nums", muted ? "text-zinc-300 dark:text-zinc-700" : "text-zinc-900 dark:text-zinc-50")}>
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{hint}</div>}
    </Card>
  );
  return to ? (
    <Link to={to} className="block focus-visible:outline-none">
      {body}
    </Link>
  ) : (
    body
  );
}

const DOES_TODAY: { to: string; title: string; text: string }[] = [
  { to: "/vault", title: "Reads your resumes", text: "Upload any number of PDF / DOCX resumes; each is parsed into structured data." },
  { to: "/profile", title: "Builds your profile", text: "One editable profile, filled from a resume of your choice. Your edits are never overwritten." },
  { to: "/memory", title: "Remembers what you can do", text: "Context cards about your skills and work, plus an ideal job description for each role you want." },
  { to: "/job-search", title: "Finds and matches jobs", text: "Planned, budgeted job searches; every job is checked against your criteria and roles, with the evidence shown." },
];

const COMING_NEXT = [
  "Jobs from many more sources: company job boards, aggregators and careers pages",
  "An agent that shortlists jobs the way you would, and learns from your choices",
  "Applications prepared for you (tailored resume, form answers), sent only with your approval",
  "A daily run that does all of this while you're away",
];

function AboutCard() {
  return (
    <Card className="p-6">
      <p className="text-xs font-medium tracking-wide text-violet-600 uppercase dark:text-violet-400">About SmartIntern</p>
      <h2 className="mt-1 font-serif text-xl text-zinc-900 dark:text-zinc-50">Your personal intern for the job hunt</h2>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
        SmartIntern learns who you are from your resume, searches for internships and jobs that fit the roles you want, and
        explains why each one matches or what it's missing. The goal: it finds, shortlists and applies for you, while you
        stay in control of what gets sent.
      </p>
      <div className="mt-5 grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">What it does today</h3>
          <ul className="mt-2 space-y-2.5">
            {DOES_TODAY.map((d) => (
              <li key={d.to} className="flex gap-2.5">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-500" />
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                  <Link to={d.to} className="font-medium text-zinc-900 hover:text-violet-700 hover:underline dark:text-zinc-100 dark:hover:text-violet-300">
                    {d.title}
                  </Link>
                  {" · "}
                  {d.text}
                </p>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Where it's going</h3>
          <ul className="mt-2 space-y-2.5">
            {COMING_NEXT.map((t) => (
              <li key={t} className="flex gap-2.5">
                <ArrowRight className="mt-0.5 size-4 shrink-0 text-zinc-400" />
                <p className="text-sm text-zinc-600 dark:text-zinc-400">{t}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}

export default function Desk() {
  const { data, error, loading, reload } = useResource(api.desk, {
    pollMs: 3000,
    shouldPoll: (d) => (d.resumes.parsing ?? 0) > 0 || (d.cards.total ?? 0) > (d.cards.embedded ?? 0) + (d.cards.failed ?? 0),
  });

  if (loading && !data) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-40" />
        <div className="grid gap-4 sm:grid-cols-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      </div>
    );
  }
  if (!data) return <ErrorBanner message={error ?? "Couldn't load your desk."} onRetry={reload} />;

  const noResumes = (data.resumes.total ?? 0) === 0;
  const parsing = data.resumes.parsing ?? 0;
  const statusEntries = Object.entries(data.status);
  const nextStep = noResumes
    ? { text: "Upload your first resume to get started.", to: "/vault", cta: "Upload resume", icon: <FileUp className="size-4" /> }
    : data.completeness < 60
      ? { text: "Fill in your profile from one of your resumes.", to: "/profile", cta: "Fill in profile", icon: <UserRound className="size-4" /> }
      : data.memory_stale || (data.cards.total ?? 0) === 0
        ? { text: "Your profile changed. Rebuild your memory cards.", to: "/memory", cta: "Open Memory", icon: <Brain className="size-4" /> }
        : !data.profile_confirmed
          ? { text: "Review your profile and confirm it's accurate.", to: "/profile", cta: "Review profile", icon: <ShieldCheck className="size-4" /> }
          : { text: "Everything is ready. Test your memory against a job description.", to: "/memory", cta: "Test a JD", icon: <Search className="size-4" /> };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-serif text-3xl tracking-tight text-zinc-900 sm:text-4xl dark:text-zinc-50">
          {greeting()}, {data.first_name ?? "there"}
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">Here's where your intern is today.</p>
      </div>

      {error && <ErrorBanner message={error} onRetry={reload} />}

      <Card className="overflow-hidden">
        <div className="flex flex-col gap-6 p-6 sm:flex-row sm:items-center">
          <ProgressRing value={data.completeness} />
          <div className="flex-1">
            <p className="text-xs font-medium tracking-wide text-violet-600 uppercase dark:text-violet-400">Next step</p>
            <p className="mt-1 text-lg font-medium text-zinc-900 dark:text-zinc-50">{nextStep.text}</p>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Profile {data.completeness}% complete
              {data.profile_confirmed ? " · confirmed" : ""}
              {parsing > 0 ? ` · parsing ${parsing} resume${parsing > 1 ? "s" : ""}…` : ""}
            </p>
          </div>
          <Link to={nextStep.to}>
            <Button variant="primary" icon={nextStep.icon}>
              {nextStep.cta}
            </Button>
          </Link>
        </div>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          to="/vault"
          icon={<FileStack className="size-4" />}
          label="Resumes"
          value={data.resumes.total ?? 0}
          hint={
            <>
              {data.resumes.parsed ?? 0} parsed
              {(data.resumes.failed ?? 0) > 0 && <span className="text-rose-500"> · {data.resumes.failed} failed</span>}
            </>
          }
        />
        <Tile
          to="/memory"
          icon={<Brain className="size-4" />}
          label="Memory cards"
          value={
            <>
              {data.cards.embedded ?? 0}
              <span className="text-base font-normal text-zinc-400"> / {data.cards.total ?? 0}</span>
            </>
          }
          hint={data.memory_stale ? <span className="text-amber-600 dark:text-amber-400">Profile changed, rebuild suggested</span> : "embedded"}
        />
        <Tile
          to="/profile"
          icon={<UserRound className="size-4" />}
          label="Profile"
          value={data.profile_confirmed ? "Confirmed" : "Draft"}
          hint={data.profile_confirmed ? "You can still edit it anytime" : "Confirm once it looks right"}
        />
        <Tile
          to="/job-search/jobs"
          icon={<Radar className="size-4" />}
          label="Job search"
          value={
            <>
              {data.job_search?.fits_preset ?? 0}
              <span className="text-base font-normal text-zinc-400"> / {data.job_search?.relevant ?? 0} relevant</span>
            </>
          }
          hint={
            data.job_search?.last_scan_at
              ? `fit your preset · ${data.job_search?.found_today ?? 0} new today · last scan ${timeAgo(data.job_search.last_scan_at)}`
              : "No scan yet. Run one from Job Search."
          }
        />
      </div>

      <AboutCard />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">System status</h2>
            <Link to="/switchboard" className="inline-flex items-center gap-1 text-xs font-medium text-violet-600 hover:underline dark:text-violet-400">
              Switchboard <ArrowRight className="size-3" />
            </Link>
          </div>
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {statusEntries.map(([key, c]) => (
              <li key={key} className="flex items-start gap-3 py-2.5">
                {c.ok ? (
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-500" />
                ) : (
                  <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-500" />
                )}
                <div className="min-w-0">
                  <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{COMPONENT_LABELS[key] ?? key}</p>
                  <p className="truncate text-xs text-zinc-500 dark:text-zinc-400" title={c.detail}>
                    {c.detail}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <div className="flex flex-col gap-4">
          <Card className="p-5">
            <h2 className="mb-3 text-sm font-semibold text-zinc-900 dark:text-zinc-100">Quick actions</h2>
            <div className="flex flex-col gap-2">
              <Link to="/vault">
                <Button className="w-full justify-start" icon={<FileUp className="size-4" />}>
                  Upload a resume
                </Button>
              </Link>
              <Link to="/profile">
                <Button className="w-full justify-start" icon={<UserRound className="size-4" />}>
                  Edit your profile
                </Button>
              </Link>
              <Link to="/memory">
                <Button className="w-full justify-start" icon={<Search className="size-4" />}>
                  Test against a JD
                </Button>
              </Link>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
