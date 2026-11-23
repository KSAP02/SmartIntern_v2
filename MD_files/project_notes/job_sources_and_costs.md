# How SmartIntern finds jobs

Rewritten 2026-11-23 from the code as it stands after Phase 2.8. Keep it current when a source,
the scan or the company finder changes. Settings named here live in `settings/config.toml`
(Admin settings edits them); raw API details live in `MD_files/api_references/`.

**Contents**
1. [The big picture: how a job gets online](#1-the-big-picture-how-a-job-gets-online)
2. [The three ways we fetch, side by side](#2-the-three-ways-we-fetch-side-by-side)
3. [Way 1: JSearch (search engine)](#3-way-1-jsearch-search-engine)
4. [Way 2: Company boards (read a company's own list)](#4-way-2-company-boards-read-a-companys-own-list)
5. [Way 3: Remote feeds](#5-way-3-remote-feeds)
6. [How your roles decide what is kept (and the "unusual role name" problem)](#6-how-your-roles-decide-what-is-kept)
7. [How location works in each way](#7-how-location-works-in-each-way)
8. [After the fetch: what happens to every job](#8-after-the-fetch-what-happens-to-every-job)
9. [The company finder](#9-the-company-finder)
10. [One scan, start to finish](#10-one-scan-start-to-finish)
11. [Costs](#11-costs)
12. [Known gaps](#12-known-gaps)

---

## 1. The big picture: how a job gets online

A recruiter at a company opens a vacancy in their **hiring system** (an "ATS": applicant tracking
system, e.g. Greenhouse, Lever, Keka). The hiring system publishes it in three kinds of places:

```
   Recruiter at Razorpay
          │  opens "Backend Engineer, Bengaluru" in its hiring system (Greenhouse)
          ▼
 ┌─────────────────────────────────────────────┐
 │ COMPANY BOARD  job-boards.greenhouse.io/razorpay │  ← the company's own, complete, live list
 │ (also shown inside razorpay.com/careers)         │    + the application form
 └─────────────────────────────────────────────┘
          │ copied / indexed by
          ├──────────────► Google for Jobs  (reads boards, LinkedIn, Naukri, Indeed…)  ← JSearch asks Google
          ├──────────────► LinkedIn, Naukri, Indeed (the company often posts there too)
          └──────────────► remote-job sites (Himalayas, RemoteJobs.org, Remotive) for remote roles
```

- A **company board** is the page (and the data behind it) where one company lists **all** its
  open jobs, run by its hiring system. Each board has an address with the company's id in it:
  `jobs.lever.co/paytm`, `job-boards.greenhouse.io/razorpay`, `swiggy.keka.com/careers`…
- The hiring system usually exposes that list as **public data** (JSON) with no key, because the
  company wants it read. That is what we read: it's free, complete, fresh, and comes with the real
  application form (good for auto-apply later).
- **Google for Jobs** collects postings from boards, LinkedIn, Naukri, etc. **JSearch** is a paid
  API that runs a Google for Jobs search for us.
- Most companies use one hiring system; we can read 9 of them. Big companies often use Workday or
  their own portal, which we can't read directly (only via JSearch).

---

## 2. The three ways we fetch, side by side

| | **JSearch** | **Company boards** | **Remote feeds** |
| --- | --- | --- | --- |
| What it is | A Google for Jobs search | The full job list of one company | Public lists of remote jobs |
| What we send | A search text: *"AI Engineer in Bengaluru"* + filters | Nothing about you: we ask for **all** of a company's jobs | Your role as a search word (2 feeds) or a category (Remotive) |
| What comes back | Up to **10 jobs** that Google ranks for that text | **Every** open job of that company, worldwide | Up to ~50 recent remote jobs per request |
| How your role is used | **By Google** (search, synonyms) and then our title check | **Only by us**, after the fetch (title words must match) | By the feed's search (2 feeds) and our title check |
| How location is used | In the search text + country = India | Only by us: keep India, or remote open to India | Feed asked for India; we keep "open to India" |
| Which companies | Any company Google knows | Only companies **in our list** (starter + discovered + finder) | Any company posting remote jobs there |
| Cost | **1 of your 200 requests a month** per request | Free (1 request per company, ~1–2 s) | Free |
| Good for applying? | Mixed (links to LinkedIn / Naukri / boards) | **Best**: the real form, mostly account-free | Mixed |
| Can be picked in Scan now | Yes (roles, location, date, query) | Yes, per hiring system | Yes, per feed |

---

## 3. Way 1: JSearch (search engine)

**What we look at:** Google's job search results for a search text.

**How a request is built** (`search_plan.py` → `sources/jsearch.py`):

| Parameter | Value (your current settings) | Meaning |
| --- | --- | --- |
| `query` | `AI Engineer in Bengaluru` (editable per scan in Scan now) | Role + place, as you'd type in Google. Several roles can be one request: `AI Engineer OR LLM Engineer in Bengaluru` |
| `country` | `in` | Search Google's India results |
| `date_posted` | "new since this search last ran" (never narrower than a week) | Don't pay for jobs we already have |
| `employment_types` | `FULLTIME` | Your job types |
| `job_requirements` | only if you have 0–2 years | Your experience bucket |
| `page` | `1` (10 jobs); page 2 only if page 1 was full and ≥ 5 were new | Smart paging |

Endpoint: `GET https://api.openwebninja.com/jsearch/search` (key in `.env`). Never retried.

**What comes back:** up to 10 jobs, each with title, company, location, description,
highlights (qualifications / responsibilities), posted date, and one or more apply links
(LinkedIn, Naukri, the company board…). Because Google searches by meaning, it returns results
even for unusual role names, but the 10 may include loosely related jobs.

**What we keep:** every returned job is stored; then (§8) its title is compared with your roles
and it lands in **Matches** or **Not relevant**. Jobs asking for more years than yours are
flagged by the Experience filter.

**Budget rules:** a request is counted **before** it is sent; 200 a month (17th → 17th), 10 kept
in reserve, 1 per scan; a search that finds nothing new 3 times in a row is run less often.

**What a result row shows** in *Scans and what they found* (illustrative numbers): "AI Engineer in
Bengaluru · 10 found · 6 new · 3 duplicates · 1 already seen".

---

## 4. Way 2: Company boards (read a company's own list)

**What we look at:** the complete job list of each company in our list (`employers` table).
**This one table is every company the scans read.** It only grows; nothing is deleted (a company
whose board stops having India jobs is switched off and looked at again later).

**Which companies, and how they get into the table:**

| How | When | Examples |
| --- | --- | --- |
| **34 starter companies** (Indian tech, global companies with India teams) | once | Flipkart, Swiggy |
| **discovered**: a stored job (JSearch, a feed) whose apply link is a board we can read | every scan, automatically (up to 10 per scan) | a startup's LinkedIn post that links to its Lever page |
| **found by the company finder** (§9): seed list, YC list, Common Crawl web index | every Find companies click | Paytm, Razorpay (seed); Analytics Vidhya, Amber Student, Athena Infonomics (web index, Keka) |

Not every company in India is covered: only the ones found these ways. The web index (§9) is what
brings in thousands of startups we'd never think of.

**Speed (2026-11-23):** boards are read **one worker per hiring system at the same time**
(Greenhouse, Lever, Keka, ... in parallel), each system still one request at a time with a 1 s
pause. 300 companies spread over 6 systems take about as long as 50 in a row.

**One company, step by step:**

```
 1. Is it due?  ── a board with nothing for your roles last time waits 7 days (weekly read)
 2. Ask for its whole list   GET api.lever.co/v0/postings/paytm   → 187 jobs listed
 3. Location check (ours)    keep India, or remote open to India  → 180 left   (7 "outside India")
 4. Title check (ours)       title has your role's words (§6)     →   2 left   (178 "title doesn't match")
 5. Details (2 systems)      SmartRecruiters / Darwinbox: 1 more request per kept job for its description
 6. Store the 2 jobs  → §8;  jobs this board no longer lists are marked expired
```

The request log shows exactly these numbers per company: *listed · outside India · title
doesn't match · kept · new*.

**The 9 hiring systems we read:**

| System | Who uses it (examples) | What we request | Agent can apply? |
| --- | --- | --- | --- |
| Greenhouse | Razorpay, Druva, many global tech | `boards-api.greenhouse.io/v1/boards/{co}/jobs` | yes |
| Lever | Paytm, Zeta, CRED | `api.lever.co/v0/postings/{co}` (100 per page) | yes |
| Ashby | newer startups | `api.ashbyhq.com/posting-api/job-board/{co}` | yes |
| SmartRecruiters | Swiggy, Upstox | `api.smartrecruiters.com/v1/companies/{co}/postings?country=in` (asks for India only) + 1 detail per kept job | yes |
| Workable | small / mid companies | `apply.workable.com/api/v1/widget/accounts/{co}` | yes |
| Recruitee | small / mid companies | `{co}.recruitee.com/api/offers/` | yes |
| Keka | Indian small / mid companies | `{co}.keka.com/careers/api/jobs/default/active` | no (CAPTCHA) → "you apply" |
| Darwinbox | larger Indian companies | `{co}.darwinbox.in/ms/candidateapi/job` (50 per page) + 1 detail per kept job | no (OTP + CAPTCHA) |
| Zoho Recruit | Indian small / mid companies | the careers page `{co}.zohorecruit.in/jobs/Careers` (jobs inside the page) | no (CAPTCHA) |

**Upkeep the system does on its own:** a board that's gone (404) is switched off; a discovered
company with no India jobs for 3 reads is switched off and retried after 30 days; when your roles
change (or you switch profile) every weekly board is read again at the next scan.

---

## 5. Way 3: Remote feeds

**What we look at:** three public remote-job sites; we keep only jobs **open to candidates in India**.

| Feed | What we request | Per scan | What comes back |
| --- | --- | --- | --- |
| Himalayas | `himalayas.app/jobs/api/search?q=<role>&country=IN&sort=recent` | 1 per role (up to 5 roles) | Recent remote jobs matching the word, hireable from India |
| RemoteJobs.org | `remotejobs.org/api/v1/jobs?q=<role>&country=IN&workArrangement=remote&limit=50` | 1 per role (up to 5) | Up to 50 remote jobs |
| Remotive | `remotive.com/api/remote-jobs?category=software-dev` | 1, at most every 8 hours | All current remote software jobs (no search; shown 24 h late) |

Then the same two checks as boards: **open to India** (from the feed's own eligibility field)
and **title matches your roles** (§6). A result row looks like (illustrative numbers): "AI
Engineer · Himalayas · 20 listed · 14 not open to India · 1 title doesn't match · 5 kept".

---

## 6. How your roles decide what is kept

There are **two title checks**, at different moments:

**A. The word check at the fetch** (boards and feeds only, `employers.title_matches`). It happens
before anything is stored, so a company's 400 unrelated jobs never enter the app.
- Each role becomes a set of **distinctive words**: abbreviations expanded (AI → artificial
  intelligence, ML → machine learning, LLM → large language model) and generic words dropped
  (engineer, developer, senior, lead, intern, associate, …).
- Each role's **search titles** from its role context (Memory → Role contexts) count as extra
  phrases.
- A job title passes if it contains **all the words of at least one phrase**.

Your current phrases (profile "My profile", roles AI Engineer and LLM Engineer):

| Phrase (from) | Words a title must contain | Passes | Fails |
| --- | --- | --- | --- |
| AI Engineer | artificial + intelligence | "Senior AI Engineer", "AI/ML Engineer", "Conversational AI Platform Architect" | "Data Scientist" |
| LLM Engineer | large + language + model | "LLM Engineer", "Large Language Model Researcher" | "NLP Engineer" |
| Applied AI Engineer (search title) | applied + artificial + intelligence | "Applied AI Scientist" | |
| Generative AI Engineer (search title) | generative + artificial + intelligence | "Generative AI Engineer", "GenAI Engineer" (GenAI is expanded) | "Prompt Engineer" |
| Machine Learning Engineer (search title) | machine + learning | "ML Engineer", "Machine Learning Scientist" | "Deep Learning Engineer" |

**B. The meaning check after storing** (all sources, §8): the title's embedding vs your roles
(similarity ≥ 0.72, or ≥ 0.60 when the job's text is close to the role context). This one decides
Matches vs Not relevant.

(Every example above was run through the real check on 2026-11-23.)

**The "unusual role name" problem — yes, you're right:**
- **Boards and feeds:** the check runs on **your role's** words. A broad role ("AI Engineer") lets
  many titles through, even "Conversational AI Platform Architect". A very specific role (say your
  role were "Conversational AI Platform Architect") needs **all** of conversational + artificial +
  intelligence + platform + architect in a job title, so most boards would keep **0** for it, and
  an ordinary "AI Engineer" job would be left out.
  What softens it: the role context's search titles (broader titles the AI writes for that role)
  also count, and generic words are ignored.
- **JSearch** does not have this problem at the fetch (Google searches by meaning), but check B
  may still put loosely related results in Not relevant.
- **What you can do today:** use roles the way companies title jobs ("AI Engineer", "Backend
  Engineer"), and edit a role's **search titles** in Memory → Role contexts to add the variants
  companies use (e.g. "GenAI Engineer", "NLP Engineer"). Those count at the fetch.
- **Possible improvement (not built):** let check A pass a title that matches a role's keywords or
  most (not all) of its words, and rely on check B for the final call.

---

## 7. How location works in each way

Your locations (Search criteria): "Bengaluru" and "Hyderabad, India". Scan now uses one at a time.

| Way | Sent to the source | Our check | What you get |
| --- | --- | --- | --- |
| JSearch | the place is **in the search text** ("… in Bengaluru") and `country=in` | none removes a job | Mostly that city; Google may fill the 10 with other Indian cities or remote |
| Company boards | nothing (SmartRecruiters: `country=in`) | keep **India, or remote open to India**; unknown location is kept | **All of India**, not just your city: a Pune job at Razorpay is kept |
| Remote feeds | `country=IN` (Himalayas, RemoteJobs.org) | keep only jobs **open to India** | Remote jobs you can do from India |

On the **Jobs page** every job shows its location against the place you searched: bold = in it,
amber "(not Karnataka)" = elsewhere in India, "remote", or "area not stated". Location never
removes a job from Matches; you decide.

---

## 8. After the fetch: what happens to every job

The same pipeline for all three ways (`job_search.ingest` → `process_new` → `compass`):

| Step | What happens | Result you see |
| --- | --- | --- |
| 1. Store once | Same source + id → updated; seen before / applied → ignored; same company + title + location from another source → **duplicate** (one row) | "new / duplicate / already seen" counts |
| 2. Facts | Job type, workplace, years asked, country, pay, **apply route** read from the text | Badges on each row; "Apply via" filter |
| 3. Embedding | OpenAI `text-embedding-3-small`: the job's digest (title + responsibilities + qualifications) and title | (internal) |
| 4. Title vs roles | Check B (§6) | **Matches** or **Not relevant** |
| 5. Role context score | Digest vs the matched role's context | Matches are **ranked** by it |
| 6. Evidence map | Each requirement vs your memory cards (exact skills, years); gaps listed | The job panel's "You have / Gaps" |

No chat-model call happens here. Switching profile re-runs steps 4–6 on stored data (no new requests).

---

## 9. The company finder

**What it does:** grows the company boards list (§4) with companies whose board **has jobs in
India**. It adds companies, not jobs: your **next scan** reads their boards.

**Where:** Admin settings → Company finder → **Find companies** (by hand; to be automated with
the agent). Runs in the background; one run at a time.

**Two tables:** `company_leads` is the **waiting list** (companies that *might* hire in India,
not checked yet or checked without luck); `employers` (§4) is **the list every scan reads**. A
lead moves into `employers` only when its board has jobs in India, so scans never waste time on
thousands of boards with nothing for you.

**Where the leads come from (all free, all public):**

| Source | What it is | How many | When it's read |
| --- | --- | --- | --- |
| **Seed list** | `services/seed_companies.csv`: Indian unicorns, startups (SaaS, fintech, AI, health, edtech, YC), product companies, global companies with India offices, from public lists | 407 | on start, when the file changes |
| **YC list** | Y Combinator companies **based in India** and still active, from the free YC open-data list (`yc-oss.github.io/api`, rebuilt daily from YC's public directory) | ~165 (140 new on 2026-11-23) | at most weekly, on a click |
| **Common Crawl web index** | a free non-profit archive that crawls billions of web pages every month and publishes an index of every address it saw. We don't crawl anything: we look up the addresses under each hiring system (`*.keka.com`, `jobs.lever.co/…`, `jobs.ashbyhq.com/…`, …). Each address names one company's board, **of any size: mostly small companies and startups** | **12,353 company boards** from the October 2026 crawl (Greenhouse ~3,900, Workable ~3,800, Ashby ~1,000, Recruitee ~800, SmartRecruiters ~640, Lever ~270, Zoho Recruit ~210, Keka ~180, Darwinbox ~15); most are outside India and drop out at the check | each click reads up to 60 index blocks; the newest 3 monthly crawls, newest first; a new crawl is picked up when it appears |

**Who is checked first** (user, 2026-11-23: startups too, not only the big names): startups and
product companies from the seed list, YC companies and companies on Indian hiring systems (Keka,
Darwinbox, Zoho Recruit) → unicorns → other web-index companies → global companies.

**One click, step by step:**

```
 1. Seed list → leads      new rows of seed_companies.csv
 2. YC list → leads        Indian YC companies not seen before (weekly)
 3. Web index → leads      up to 60 blocks of the Common Crawl index files (3,000 addresses each);
                           continues where it stopped next click
 4. Check, at the same time:
      ▸ up to 300 companies whose board is known (web index, careers links): one worker per
        hiring system, one board read each, 1 s apart per system
      ▸ up to 40 companies whose board has to be searched for (seed, YC), one worker:
          a. careers page: robots.txt first, then /careers, /jobs, … ; look for a board link
          b. name guess: "razorpay" tried on Greenhouse, Lever, Ashby, Keka, Darwinbox,
             Workable, SmartRecruiters, Recruitee; first hit wins
 5. Each board read once (same India + title checks as a scan)
 6. Verdict:  jobs in India → KEPT: added to employers (every scan reads it from now on)
              no India jobs → check again in 30 days
              no board      → check again in 90 days
```

**Results so far (2026-11-23):**
- First click (seed list, unicorns first then): 40 checked → **7 kept** (Paytm 180 India jobs,
  Swiggy 156, Zeta 29, Razorpay 24, Druva 12, CRED 11, Upstox 1); 32 had no board we read (many
  big companies use Workday or their own portal).
- The web index first failed: Common Crawl's query server answered every request with HTTP 504
  (overloaded). **Fixed** by reading the index files directly from Common Crawl's S3 storage
  (`crawl_index.py`): 12,353 boards in ~3 minutes.
- A test run of 35 checks (mostly Keka companies from the web index) → **26 kept**: Indian
  startups such as Analytics Vidhya, Amber Student, Athena Infonomics, Aiden AI, Acuiti Labs, in
  1.5 minutes.

**It runs by itself (user, 2026-11-23).** While the backend runs, the 30-second timer
(`scheduler.py` → `company_finder.auto_tick`) starts the next run **30 s after the last one ends**
as long as companies are due (or a crawl is half read). When nothing is due it looks again
**every 6 hours** (a new monthly crawl, new YC companies, re-check dates). Never during a scan;
after a failed run it waits 15 minutes. **Run now** (Admin settings → Company finder, or the
Company finder page) starts one at once. All in `[scout.search.finder]`: `auto`,
`pause_between_runs_seconds`, `idle_check_hours`, `error_backoff_minutes`.

**Run size (chosen 2026-11-23):** up to **500** companies whose board is known + **50** whose board
has to be searched for, and up to 60 web-index blocks. That's ~5–10 minutes a run: small enough
that a restart loses little and each run is a readable row on the dashboard, big enough to clear
the backlog in a few hours. A restart mid-run keeps everything already checked (each company is
saved as it's checked); the run is marked *interrupted* and the next one carries on.

**Analytics: Admin → Company finder** (`/company-finder`): current run with a progress bar; tiles
(companies scans read, kept, checked, waiting, India jobs on kept boards, runs); a stacked bar per
run (kept / no jobs in India / no board / couldn't be read); every run (new on the list, checked,
kept, kept rate, India jobs, duration, auto or by you), each opening to its companies kept and its
hiring systems; all companies **by hiring system** and **by where they came from** with kept rates.

**First automatic runs (2026-11-23):** run 1 read the September and August crawls (+5,129
companies) and checked 200 companies before a restart: **115 kept** (Keka and Zoho Recruit
startups), then run 2 started by itself. Companies scans read: 63 → 179.

**What "kept" means:** the board has at least one job in India or remote and open to India (the
same check as a scan). Companies whose jobs are all elsewhere are not kept.

**Cost:** free. Runs use the network in the background; no JSearch, no OpenAI.

**Only on localhost (user, 2026-11-23).** `COMPANY_FINDER=false` in a server's env (the
deployed backend) switches the finder off there: no automatic runs, no Run now (the API
answers 400); the Company finder page still shows the runs in its database. Scans on that
server read the companies found locally once the database is shared (Phase 7: hosted
Postgres + a copy script; see `project_build_phases/README.md`).

---

## 10. One scan, start to finish

```
 Scan now (or the schedule)
   │
   ├─ 1. JSearch ............ planned requests within the budget          (Way 1)
   ├─ 2. Remote feeds ....... 1 request per role per feed                 (Way 3)
   ├─ 3. Discover companies . stored jobs whose apply link is a board → add the company
   ├─ 4. Company boards ..... every due company in the list, one worker per system (Way 2)
   ├─ 5. Process ............ store once, facts, embeddings, Matches / Not relevant, ranking
   ├─ 6. Evidence map ....... requirements vs your memory cards
   └─ 7. Prune .............. discarded jobs older than 3 days deleted
```

Every request is logged; **Scan Jobs → Scans and what they found** shows one row per scan, then
each source's requests with their counts, then each request's jobs and where each job is now.

---

## 11. Costs

| What | Money | Limit | Time |
| --- | --- | --- | --- |
| JSearch | free plan (paid plans exist) | **200 requests / billing period**, 10 jobs each | ~1–5 s per request |
| Company boards (9 systems) | free | none (1 s between companies of one system; systems in parallel) | ~1–2 s per company, divided by the number of systems |
| Remote feeds (3) | free | Remotive: once per 8 h | ~1 s per request |
| Company finder (by hand) | free | one request at a time per site | ~3–8 min per click (300 known boards + 40 searched for) |
| OpenAI embeddings (each new job) | ~300–500 tokens per job; at `text-embedding-3-small`'s published price (about $0.02 per million tokens) ~1,000 jobs ≈ 1 cent (check current pricing) | your OpenAI account | batched |
| OpenAI chat: role contexts | 1 call per role, when added, first used by a profile, or on Regenerate | your OpenAI account | a few seconds |

Not part of fetching but also on OpenAI: resume parsing (1 call per resume), "Group by theme".

---

## 12. Known gaps

- **Unusual role names** get few or no board / feed results at the fetch (§6).
- **Workday, SuccessFactors, iCIMS, custom portals** (many large employers in India) are read only
  through JSearch. Workday is the biggest gap.
- **Naukri, LinkedIn, Instahyre, Wellfound** have no legal, free API; only via JSearch (quota).
- **More kept companies = longer scans.** Every kept company's board is read each scan (weekly
  when it had nothing for your roles). With hundreds kept, the board step can take several
  minutes; parallel reading per system keeps it down.
- **Startup India (government list)** isn't used: no documented API, and most entries have no
  website or careers page to find a board from.
- **Change detection** (ETag / 304) isn't used: an unchanged board is still read in full.
- **Keka / Darwinbox / Zoho Recruit** jobs are found, but the agent can't apply (CAPTCHA / OTP).
