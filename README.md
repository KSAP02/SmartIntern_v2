# SmartIntern

**An AI job-search assistant that learns who you are from your resume, finds internships and
jobs that fit, and (later) prepares and sends applications for you.**

You upload your resume once. SmartIntern turns it into an editable profile and a set of
"context" cards about your skills and experience. It then searches job listings for the
roles you want, filters out what doesn't fit, and shows you why each remaining job matches
(or what it's missing).

> **Status:** early, actively developed, single user. Phases 1–2.6 are built (profile, memory,
> job search, matching). Applying for you, the daily agent and multi-user login are planned.
> See [the phase plans](MD_files/project_build_phases/README.md).

---

## What it does today

| Area | Page | What you can do |
| --- | --- | --- |
| **Vault** | `/vault` | Upload as many resumes as you like (PDF / DOCX). Each one is parsed into structured data. |
| **My Profile** | `/profile` | Your editable profile. **Fill in using resume** previews the changes and only fills empty fields by default, so your edits are never overwritten. Skills are grouped by theme. |
| **Memory** | `/memory` | **Cards**: short, editable facts about you (one per skill group, job, project …). **Role contexts**: for each role you want, an AI-written "ideal job description" that every fetched job is compared against. |
| **Job Search → Scan Jobs** | `/job-search` | Pick roles, see exactly which requests will be sent and what they cost (dry run), then scan. Each request shows the jobs it returned and what happened to them. |
| **Job Search → Jobs** | `/job-search/jobs` | Matches / Selected / Applied / Discarded / Not relevant / Excluded tabs. Each job has a panel showing how well it matches and which requirements you meet or miss. |
| **Search Settings** | `/job-search/settings` | Roles, job types, workplace, locations, experience, and the "apply preset" (pay, salary …). |
| **Admin** | `/admin`, `/jsearch`, `/switchboard` | Models and thresholds (backed by `settings/config.toml`), API budget and usage analytics, system status. |

## How it works

```
resume ──► parsed profile ──► memory cards ──► role contexts (one per target role)
                                                     │
job APIs ──► jobs ──► criteria check (type, place, years) ──► title vs your roles
                                                     │
                       job text vs role context (embeddings) ──► Matches, ranked
                                                     │
                     requirements ↔ your skills ──► "meets / missing" evidence per job
```

- **Search budget first.** The job API (JSearch) has a monthly request quota, so every scan is
  planned and shown before anything is sent, and it can never go over the budget.
- **No black box.** Every job shows its scores, why it was kept or dropped, and the evidence.
- **Your call wins.** Moving a job to Matches or Not relevant overrides the automatic checks.

## Tech stack

| Layer | Choice |
| --- | --- |
| Backend | Python, FastAPI, SQLModel on SQLite |
| Vectors | Milvus Lite (local file) behind a small seam, so it can move to a Milvus server |
| AI | OpenAI: chat model for resume parsing and role contexts, `text-embedding-3-small` for matching. Provider and model are config, not code. |
| Frontend | Vite + React + TypeScript + Tailwind, served by a small Node server that proxies `/api` |
| Jobs | JSearch (Google for Jobs) via OpenWeb Ninja / RapidAPI. More sources are planned ([Phase 2.7](MD_files/project_build_phases/phase_2_7_india_first_multi_source_discovery.md)). |
| Packaging | Docker Compose (`backend` + `frontend`) |

## Run it locally

You need Docker, an OpenAI API key and, for job search, a JSearch API key.

```bash
git clone https://github.com/KSAP02/SmartIntern_v2.git
cd SmartIntern_v2
cp .env.example .env          # then put your keys in .env
docker compose up --build     # open http://localhost:3000
```

Then:

1. Upload a resume in **Vault**.
2. Fill **My Profile** from it.
3. Add the roles you want in **Search Settings**.
4. Run a scan from **Scan Jobs**.

Data (database, resume files, vectors) lives in the `appdata` Docker volume.
`docker compose down -v` deletes it.

Backend tests (offline, no API calls):

```bash
docker compose run --rm --no-deps backend pytest backend/tests -q
```

## Configuration

- **`.env`**: secrets and infrastructure only (API keys, paths, URLs). Never committed; see
  `.env.example`.
- **`settings/config.toml`**: everything tunable (models, temperature, thresholds, search
  budget, schedule). Commented line by line. Also editable from **Admin settings** in the app.
  Changes apply without a restart.

## Project layout

```
backend/            FastAPI app: api/<wing>/<room>.py routers, services/, db, model and vector seams, tests
frontend/           React app (web/) + Node server (src/server.ts)
settings/           config.toml
mcp-server/         optional MCP bridge into the backend API
MD_files/           design docs: phase plans, database schema, API references
docker-compose.yml
```

## Roadmap

1. ✅ Candidate foundation: resumes, profile, memory
2. 🔍 Job search and matching (JSearch, role contexts)
3. 📝 Jobs from many sources (company job boards, aggregators, careers pages)
4. Scoring and an agent that selects jobs the way you would
5. Preparing applications (tailored resume, answers), with your approval
6. A daily agent and controlled auto-apply
7. Deployment with login, Postgres, object storage

## Privacy

SmartIntern handles personal data (contact details, work history).

- It is built for **one user** and has **no login yet**. Don't expose a deployment with
  real data publicly until authentication is added.
- Resumes and the database stay in your own storage.
- Only job search terms are sent to job APIs.
- Resume text is sent to the AI provider you configure.
