"""Job text: HTML -> text, requirement chunks, identity keys. All sample data is fake."""
from backend.job_schemas import NormalizedJob
from backend.services.job_text import (
    canonical_url,
    chunk_requirements,
    content_hash,
    dedupe_key,
    html_to_text,
    job_plain_text,
    normalize_company,
    normalize_title,
)

GREENHOUSE_HTML = """
<div class="content">
  <p><strong>Exampleco</strong> builds tools for fictional logistics teams.&nbsp;We are a
  small, remote-friendly team.</p>
  <h3>What you'll do</h3>
  <ul>
    <li><p>Design and build backend services in Python &amp; FastAPI</p></li>
    <li>Own features end to end, from schema to dashboards
      <ul><li>Write clear technical docs for each feature</li></ul>
    </li>
  </ul>
  <p><strong>What we're looking for</strong></p>
  <ul>
    <li>2+ years of experience with Python and PostgreSQL</li>
    <li>Solid understanding of REST APIs and HTTP</li>
    <li>Experience with Kubernetes is a plus</li>
  </ul>
  <p><b>Nice to have</b></p>
  <ul><li>Familiarity with vector databases and RAG</li></ul>
  <h4>Benefits</h4>
  <ul><li>Learning budget of a made-up amount every year</li></ul>
  <p>Exampleco is an equal opportunity employer and considers applicants without regard to race or religion.</p>
  <script>trackEverything()</script>
  <style>.x{color:red}</style>
</div>
"""

PLAIN_INDIAN_INTERNSHIP = """About Fakecorp
Fakecorp Labs is hiring a Data Science Intern for its Pune office.

Responsibilities:
- Clean and analyse datasets with Pandas and SQL
- Build dashboards for the operations team

Requirements:
- Pursuing a B.Tech in Computer Science or related field
- Good knowledge of Python, e.g. NumPy and Pandas. Must be available for 6 months.
- Knowledge of Tableau is preferred

Stipend: INR 20,000 per month
Duration: 6 months
"""

MARKDOWN_JD = """# Machine Learning Engineer
We build imaginary robots. Our team is tiny.

## Minimum Qualifications
* 3+ years building ML systems in production
* Strong Python skills

## Preferred Qualifications
* Experience with PyTorch

**Who you are**
- You enjoy writing tests for your models and pipelines
"""


def test_html_to_text_structure():
    text = html_to_text(GREENHOUSE_HTML)
    lines = text.split("\n")
    assert "What you'll do:" in lines
    assert "What we're looking for:" in lines
    assert "Nice to have:" in lines
    assert "- Design and build backend services in Python & FastAPI" in lines
    assert "- Write clear technical docs for each feature" in lines
    assert "trackEverything" not in text and "color:red" not in text
    assert "\n\n\n\n" not in text
    assert " " not in text


def test_html_to_text_empty_and_br():
    assert html_to_text("") == ""
    assert html_to_text("<p>Line one<br>Line two</p>") == "Line one\nLine two"


def test_job_plain_text_prefers_text_and_converts_html():
    job = NormalizedJob(source="x", source_job_id="1", title="T", description_text="Plain text body.")
    assert job_plain_text(job) == "Plain text body."
    job = NormalizedJob(source="x", source_job_id="1", title="T", description_html="<ul><li>A bullet</li></ul>")
    assert job_plain_text(job) == "- A bullet"
    job = NormalizedJob(source="x", source_job_id="1", title="T", description_text="<p>Hi <b>there</b></p>")
    assert "<" not in job_plain_text(job)
    assert job_plain_text(NormalizedJob(source="x", source_job_id="1", title="T")) == ""


def _by_text(chunks, needle):
    return next(c for c in chunks if needle in c.text)


def test_chunk_greenhouse_sections():
    chunks = chunk_requirements(html_to_text(GREENHOUSE_HTML))
    assert _by_text(chunks, "fictional logistics").section == "about"
    c = _by_text(chunks, "Design and build backend")
    assert (c.section, c.importance) == ("responsibilities", "unknown")
    assert _by_text(chunks, "technical docs").section == "responsibilities"
    c = _by_text(chunks, "2+ years of experience")
    assert (c.section, c.importance) == ("requirements", "must")
    c = _by_text(chunks, "Kubernetes is a plus")  # "nice to have" inside a requirements list
    assert (c.section, c.importance) == ("requirements", "nice")
    c = _by_text(chunks, "vector databases")
    assert (c.section, c.importance) == ("nice_to_have", "nice")
    assert _by_text(chunks, "Learning budget").section == "benefits"
    c = _by_text(chunks, "equal opportunity")
    assert (c.section, c.importance) == ("other", "unknown")
    assert [c.position for c in chunks] == list(range(len(chunks)))
    assert all(15 <= len(c.text) <= 401 for c in chunks)


def test_chunk_plain_text_and_sentences():
    chunks = chunk_requirements(PLAIN_INDIAN_INTERNSHIP)
    assert _by_text(chunks, "Fakecorp Labs is hiring").section == "about"
    assert _by_text(chunks, "Clean and analyse").section == "responsibilities"
    c = _by_text(chunks, "Pursuing a B.Tech")
    assert (c.section, c.importance) == ("requirements", "must")
    # a long bullet stays one chunk; "e.g." does not split anything
    assert _by_text(chunks, "e.g. NumPy").section == "requirements"
    c = _by_text(chunks, "Tableau is preferred")
    assert c.importance == "nice"
    assert _by_text(chunks, "INR 20,000").section == "benefits"


def test_chunk_markdown_headings():
    chunks = chunk_requirements(MARKDOWN_JD)
    c = _by_text(chunks, "3+ years building")
    assert (c.section, c.importance) == ("requirements", "must")
    c = _by_text(chunks, "PyTorch")
    assert (c.section, c.importance) == ("nice_to_have", "nice")
    assert _by_text(chunks, "writing tests").section == "requirements"
    assert _by_text(chunks, "imaginary robots").section == "about"


def test_chunk_paragraph_split_and_limits():
    para = ("You will work on data pipelines. You will also review code from teammates every week. "
            "Ok. We value curiosity and ownership in everything we do.")
    chunks = chunk_requirements("Responsibilities:\n" + para)
    texts = [c.text for c in chunks]
    assert "You will work on data pipelines." in texts
    assert "Ok." not in texts  # under 15 chars
    long = "- " + "word " * 200
    assert len(chunk_requirements(long)[0].text) <= 401
    many = "\n".join(f"- Requirement number {i} with words" for i in range(100))
    assert len(chunk_requirements(many, max_chunks=10)) == 10


def test_pre_heading_requirement_bullets():
    chunks = chunk_requirements("- 2+ years of experience with Go\n- Knowledge of SQL databases")
    assert all(c.section == "requirements" for c in chunks)
    assert all(c.importance == "unknown" for c in chunks)


def test_short_skill_line_is_not_a_heading():
    chunks = chunk_requirements("Requirements:\nStrong communication skills\nPython and SQL experience")
    assert _by_text(chunks, "communication skills").section == "requirements"


def test_normalize_company():
    assert normalize_company("Acme Technologies Pvt. Ltd.") == "acme technologies"
    assert normalize_company("Initech, Inc.") == "initech"
    assert normalize_company("Globex GmbH") == "globex"
    assert normalize_company("Co") == "co"
    assert normalize_company(None) == ""


def test_normalize_title():
    assert normalize_title("Software Engineer (m/f/d) - Backend") == "software engineer backend"
    assert normalize_title("Sr. C++ Developer [Remote]") == "senior c++ developer"


def test_dedupe_key():
    a = dedupe_key("Acme, Inc.", "Data Analyst (Remote)", "Remote - US")
    b = dedupe_key("ACME", "Data Analyst", "Remote (United States)")
    assert a == b == "acme|data analyst|remote"
    assert dedupe_key("Acme", "Intern", "Bangalore, India") == dedupe_key("Acme", "Intern", "Bengaluru")
    assert dedupe_key(None, "Intern", None) == "|intern|"


def test_canonical_url():
    u = "HTTP://www.Example.com/jobs/123/?utm_source=x&gh_src=abc&gh_jid=123&lever-origin=applied#apply"
    assert canonical_url(u) == "https://example.com/jobs/123?gh_jid=123"
    assert canonical_url("https://jobs.example.com/a/") == canonical_url("https://jobs.example.com/a")
    assert canonical_url(None) is None
    assert canonical_url("  ") is None


def test_content_hash():
    h1 = content_hash("Data Analyst", "Some   text\nhere")
    h2 = content_hash("data analyst", "Some text here")
    assert h1 == h2 and len(h1) == 64
    assert content_hash("Data Analyst", "Other text") != h1


def test_logistics_block_and_inline_labels_are_not_requirements():
    text = """Requirements
- 3+ years of Python experience
Logistics:
Minimum education: Bachelor's degree or an equivalent combination of education and experience
Visa sponsorship: We do sponsor visas! However, we can't sponsor every role.
We encourage you to apply even if you do not believe you meet every single qualification.
Find Jobs in Germany on Arbeitnow
Find more English Speaking Jobs in United Kingdom on Arbeitnow
The annual compensation range for this role is listed below."""
    chunks = chunk_requirements(text)
    reqs = [c.text for c in chunks if c.section == "requirements"]
    assert reqs == ["3+ years of Python experience"]
    assert all(c.section == "other" for c in chunks if "visa" in c.text.lower() or "Bachelor" in c.text)
    assert all(c.section == "other" for c in chunks if "Arbeitnow" in c.text or "compensation" in c.text)


def test_inline_label_applies_to_its_own_line_only():
    text = """About the company
We build tools for teams.
Minimum education: Bachelor's degree in Computer Science or similar
Our office is in Berlin and we love coffee and long walks."""
    chunks = {c.text: c for c in chunk_requirements(text)}
    assert chunks["Bachelor's degree in Computer Science or similar"].section == "requirements"
    assert chunks["Our office is in Berlin and we love coffee and long walks."].section == "about"


def test_title_variants_split_long_titles_and_expand_abbreviations():
    from backend.services.job_text import expand_abbreviations, title_variants

    v = title_variants("Entry-Level Machine Learning Engineer (LLM & AI Agent Specialist)")
    assert "Machine Learning Engineer" in v
    assert "large language model & artificial intelligence Agent Specialist" in v
    assert "Mechanical Engineer" in title_variants("Mechanical Engineer - Fresher")
    assert all("Fresher" not in x for x in title_variants("Mechanical Engineer - Fresher")[1:])
    assert expand_abbreviations("ML Engineer") == "machine learning Engineer"
    assert expand_abbreviations("HTML Developer") == "HTML Developer"  # whole words only
