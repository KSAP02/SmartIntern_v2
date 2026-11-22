# Indian hiring systems (ATS): Keka, Darwinbox, Zoho Recruit (Phase 2.7 E)

Collected 2026-11-22 from public careers pages, their robots.txt and the providers' terms; about 20
live GETs, no form submitted. Trimmed real responses are test fixtures in
`backend/tests/fixtures/indian_ats/`.

| System | Job list (no key) | robots / terms | Application form | Built |
| --- | --- | --- | --- | --- |
| Keka Hire | `GET https://{tenant}.keka.com/careers/api/jobs/default/active` (JSON list, full descriptions) | robots: `Disallow: /`, `Allow: /careers`; terms bind subscribers, silent on reading public pages | No account, but an image CAPTCHA (`#imgCaptcha`, `/careers/iscaptchavalid`) | Yes, for finding (`sources/keka.py`); apply = needs you |
| Darwinbox | `GET https://{tenant}.darwinbox.in/ms/candidateapi/job?page=N&limit=50` (no description) + `GET .../job/{id}` (detail: `jd` HTML-escaped, `is_remote`) | careers host has no robots.txt; terms silent | Candidate login / OTP and a Cloudflare Turnstile CAPTCHA | Yes, for finding (`sources/darwinbox.py`); details only for jobs passing the pre-check |
| Zoho Recruit | No JSON: the careers page `https://{co}.zohorecruit.{in,com,eu}/jobs/Careers` holds the list as HTML-escaped JSON in `<input id="jobs" value="[...]">` (~2 MB page) | robots allows `/jobs/*`, `/careers`; terms silent | Job page has a CAPTCHA | Yes, for finding (`sources/zohorecruit.py`); not tried by name guessing (page size) |
| Freshteam | Token API only | — | — | **No**: Freshworks is retiring Freshteam (renewals stop Mar–Jun 2026) |
| TurboHire | no public pattern found | — | — | No |

Fields used:
- **Keka:** `id`, `title`, `description` / `excerpt` (HTML), `jobLocations[] {city, state, countryCode, countryName}`, `jobType` (1 part-time, 2 full-time), `publishedOn`, `experience`. Job page `https://{t}.keka.com/careers/jobdetails/{id}`.
- **Darwinbox:** list `message.jobs[] {id, title, officelocation_show_arr, emp_type ("Permanent"), job_posting_on (unix s), created_on}`, `message.jobscount`; detail `message.job[0] {jd, is_remote, experience}`. Unknown tenant → HTTP 500 "Invalid subdomain".
- **Zoho Recruit:** `id`, `Posting_Title` / `Job_Opening_Name`, `City`, `State`, `Country`, `Job_Type`, `Job_Description` (text), `Date_Opened`, `Publish`, `Remote_Job` (unverified). An earlier `id="jobs"` input holds portal settings: the one whose value is a list is used. Board id = subdomain + "." + Zoho's data-centre TLD (`moneyforward.in`). Pagination beyond the first page: unverified.

Example boards: `pennanttech.keka.com/careers`, `spyneai.keka.com/careers`,
`cars24.darwinbox.in/ms/candidate/careers`, `zepto.darwinbox.in/ms/candidate/careers`,
`moneyforward.zohorecruit.in/jobs/Careers`, `increff.zohorecruit.com/careers`.
