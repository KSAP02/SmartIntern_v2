"""Job facts by rules: category, workplace, places, pay, seniority, years, visa, location match.
All sample postings are fake."""
import pytest

from backend.job_schemas import NormalizedJob
from backend.services.job_facts import (
    FACT_KEYS,
    _parse_salary,
    derive_facts,
    location_match,
    resolve_place,
)


def _job(title, location=None, **kw):
    return NormalizedJob(source="test", source_job_id="1", title=title, location_text=location, **kw)


INDIA_INTERNSHIP = """About Fakecorp
Fakecorp Labs builds pretend analytics software.

Responsibilities:
- Clean datasets with Pandas

Who can apply:
- Students pursuing B.Tech, available for a 6-month internship
- 0-1 years of experience

Stipend: ₹25,000/month
Start date: Immediately
Apply by 30 Dec 2026
"""

US_REMOTE = """Initech (fictional) is hiring a Senior Backend Engineer.
This is a fully remote, full-time position open to candidates in the US only.

Requirements:
- 5+ years of professional experience building APIs
- At least 2 years with Kubernetes
- 10 years in business, founded by imaginary people

Compensation: The base salary range is $140k–$180k plus equity.
We are unable to sponsor visas for this role.
"""

EU_HYBRID = """Globex is an invented company in Berlin.
We work in a hybrid model: 3 days a week in the office.

What you bring:
- Minimum 3 yrs of experience with Go, and at least 1 year with Kafka
- 8+ years with Java preferred

Salary: €60.000 - €75.000 per year. Visa sponsorship available.
"""


def test_keys_exact():
    f = derive_facts(_job("Engineer"), "")
    assert set(f) == set(FACT_KEYS) | {"field_sources"}
    assert f["country_codes"] == [] and f["remote_regions"] == []
    assert f["field_sources"] == {}


def test_india_internship():
    f = derive_facts(_job("Data Science Intern", "Pune, Maharashtra, India"), INDIA_INTERNSHIP)
    assert f["category"] == "internship"
    assert f["seniority"] == "intern"
    assert f["country_codes"] == ["IN"]
    assert f["compensation_type"] == "stipend"
    assert (f["salary_min"], f["salary_max"], f["salary_currency"], f["salary_period"]) == (25000, None, "INR", "month")
    assert f["internship_duration"] == "6 months"
    assert f["min_years_experience"] == 0
    assert f["start_date"] == "Immediately"
    assert f["apply_deadline"] == "30 Dec 2026"
    assert f["visa_sponsorship"] is None
    assert f["field_sources"]["category"] == "rules"
    assert "workplace_type" not in f["field_sources"]


def test_us_remote_fulltime():
    f = derive_facts(_job("Senior Backend Engineer", "Remote (US only)"), US_REMOTE)
    assert f["category"] == "full_time"
    assert f["workplace_type"] == "remote"
    assert f["remote_regions"] == ["US"]
    assert f["country_codes"] == ["US"]
    assert f["seniority"] == "senior"
    assert (f["salary_min"], f["salary_max"], f["salary_currency"], f["salary_period"]) == (140000, 180000, "USD", "year")
    assert f["compensation_type"] == "paid"
    assert f["min_years_experience"] == 2  # the lowest stated requirement; "10 years in business" ignored
    assert f["visa_sponsorship"] == "no"


def test_eu_hybrid():
    f = derive_facts(_job("Backend Developer", "Berlin, Germany"), EU_HYBRID)
    assert f["workplace_type"] == "hybrid"
    assert f["country_codes"] == ["DE"]
    assert (f["salary_min"], f["salary_max"], f["salary_currency"], f["salary_period"]) == (60000, 75000, "EUR", "year")
    assert f["min_years_experience"] == 1  # "8+ years ... preferred" is skipped
    assert f["visa_sponsorship"] == "yes"
    assert f["category"] is None  # never inferred from absence
    assert f["seniority"] is None


def test_source_values_win():
    job = _job(
        "Software Engineering Intern", "Anywhere", is_remote=True, category="part_time",
        salary_min=1000, salary_max=2000, salary_currency="usd", salary_period="month",
    )
    f = derive_facts(job, "Full-time internship. Salary $5,000 per month.")
    assert f["category"] == "part_time"
    assert f["workplace_type"] == "remote"
    assert (f["salary_min"], f["salary_currency"]) == (1000, "USD")
    assert f["remote_regions"] == ["WORLDWIDE"]
    src = f["field_sources"]
    assert src["category"] == src["workplace_type"] == src["salary_min"] == "source"
    assert src["remote_regions"] == "rules"


def test_category_rules():
    assert derive_facts(_job("Marketing Trainee"), "")["category"] == "internship"
    assert derive_facts(_job("Designer (Part-time)"), "")["category"] == "part_time"
    assert derive_facts(_job("Freelance Copywriter"), "")["category"] == "freelance"
    assert derive_facts(_job("DevOps Contractor"), "")["category"] == "contract"
    assert derive_facts(_job("Engineer"), "This is a full-time, permanent role.")["category"] == "full_time"
    assert derive_facts(_job("Engineer"), "Part-time or full-time possible.")["category"] is None
    assert derive_facts(_job("Engineer"), "You will mentor our interns.")["category"] is None
    # title beats description
    assert derive_facts(_job("Product Intern"), "full-time")["category"] == "internship"
    assert derive_facts(_job("International Sales Lead"), "")["category"] is None


def test_workplace_rules():
    assert derive_facts(_job("Dev", "Hybrid - London"), "")["workplace_type"] == "hybrid"
    assert derive_facts(_job("Dev", "Bengaluru (On-site)"), "")["workplace_type"] == "onsite"
    assert derive_facts(_job("Dev"), "We are a remote-first company.")["workplace_type"] == "remote"
    assert derive_facts(_job("Dev"), "Work from home allowed for this role.")["workplace_type"] == "remote"
    assert derive_facts(_job("Dev"), "Experience with hybrid cloud setups.")["workplace_type"] is None
    assert derive_facts(_job("Dev"), "We collaborate with remote teams.")["workplace_type"] is None
    assert derive_facts(_job("Dev"), "On-site interviews in Pune.")["workplace_type"] is None
    assert derive_facts(_job("Dev"), "This role is in-office five days a week.")["workplace_type"] == "onsite"


def test_seniority_rules():
    cases = {
        "Junior Data Analyst": "entry", "Graduate Engineer": "entry", "Fresher - Java Developer": "entry",
        "Sr. Software Engineer": "senior", "Staff Engineer": "lead", "Principal Scientist": "lead",
        "Head of Data": "lead", "Mid-Level QA Engineer": "mid", "Lead Generation Intern": "intern",
        "Software Engineer": None,
    }
    for title, want in cases.items():
        assert derive_facts(_job(title), "")["seniority"] == want, title


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Stipend: ₹25,000/month", (25000, None, "INR", "month")),
        ("Stipend INR 25k per month", (25000, None, "INR", "month")),
        ("Stipend: Rs. 30,000", (30000, None, "INR", "month")),
        ("CTC: 12 LPA", (1200000, None, "INR", "year")),
        ("Package 12-15 LPA", (1200000, 1500000, "INR", "year")),
        ("CTC ₹ 8,00,000 per annum", (800000, None, "INR", "year")),
        ("Salary: 6 lakhs per annum", (600000, None, "INR", "year")),
        ("Salary $90k–$110k", (90000, 110000, "USD", "year")),
        ("Pay: $90-110k", (90000, 110000, "USD", "year")),
        ("$45/hr", (45, None, "USD", "hour")),
        ("Rate: $45 per hour", (45, None, "USD", "hour")),
        ("€50.000 - €60.000", (50000, 60000, "EUR", None)),
        ("Salary €50.000 - €60.000", (50000, 60000, "EUR", "year")),
        ("Base salary USD 120,000", (120000, None, "USD", "year")),
        ("£35,000 - £45,000 a year", (35000, 45000, "GBP", "year")),
        ("Salary: 55 000 EUR annually", (55000, None, "EUR", "year")),
    ],
)
def test_salary_formats(text, expected):
    sal = _parse_salary(text)
    if expected[3] is None:  # range with no pay word and no period: still a range, period unknown
        assert sal is None or (sal["min"], sal["max"], sal["currency"]) == expected[:3]
        return
    assert sal is not None, text
    assert (sal["min"], sal["max"], sal["currency"], sal["period"]) == expected


@pytest.mark.parametrize(
    "text",
    [
        "3-5 years of experience",
        "We raised $50M in funding",
        "A $1,000 home office setup budget",
        "Our 401(k) plan",
        "Work 40 hours per week",
    ],
)
def test_salary_not_found(text):
    assert _parse_salary(text) is None


def test_compensation_types():
    assert derive_facts(_job("Design Intern"), "This is an unpaid internship.")["compensation_type"] == "unpaid"
    assert derive_facts(_job("Design Intern"), "Stipend: None")["compensation_type"] == "unpaid"
    assert derive_facts(_job("Design Intern"), "A paid internship for students.")["compensation_type"] == "paid"
    assert derive_facts(_job("Design Intern"), "Monthly stipend provided.")["compensation_type"] == "stipend"
    # an office "stipend" in a full-time job is not the pay type
    f = derive_facts(_job("Engineer"), "Perks: home office stipend. Salary $100k-$120k per year.")
    assert f["compensation_type"] == "paid"
    assert derive_facts(_job("Engineer"), "Great team.")["compensation_type"] is None


@pytest.mark.parametrize(
    "text,years",
    [
        ("3+ years of experience in Python", 3),
        ("At least 2 years experience with SQL", 2),
        ("2-4 years of experience", 2),
        ("Minimum 5 yrs exp in sales", 5),
        ("We have been in business for 10 years.", None),
        ("Candidates must be 18 years old.", None),
        ("Company with 25 years of history", None),
        ("A 4 years degree program", None),
    ],
)
def test_min_years(text, years):
    assert derive_facts(_job("Engineer"), text)["min_years_experience"] == years


def test_internship_duration():
    f = lambda t: derive_facts(_job("Intern"), t)["internship_duration"]  # noqa: E731
    assert f("Duration: 12 weeks") == "12 weeks"
    assert f("This is a 3-month internship.") == "3 months"
    assert f("Internship period of 3-6 months") == "3-6 months"
    assert f("You will present your work within 2 months of joining") is None
    assert derive_facts(_job("Engineer"), "A 6 months project")["internship_duration"] is None


def test_visa():
    v = lambda t: derive_facts(_job("Engineer"), t)["visa_sponsorship"]  # noqa: E731
    assert v("Visa sponsorship available for the right candidate.") == "yes"
    assert v("We sponsor visas.") == "yes"
    assert v("No visa sponsorship available.") == "no"
    assert v("Must be authorized to work in the US without sponsorship.") == "no"
    assert v("We are not able to sponsor work visas.") == "no"
    assert v("Great culture.") is None


def test_places_and_remote_regions():
    f = derive_facts(_job("Dev", "San Francisco, CA"), "")
    assert f["country_codes"] == ["US"]
    f = derive_facts(_job("Dev", "Pune, IN"), "")
    assert f["country_codes"] == ["IN"]
    f = derive_facts(_job("Dev", "Bangalore; Gurgaon; London, UK"), "")
    assert f["country_codes"] == ["IN", "GB"]
    f = derive_facts(_job("Dev", "Remote - Europe"), "")
    assert (f["workplace_type"], f["remote_regions"]) == ("remote", ["EU"])
    f = derive_facts(_job("Dev", "Remote (EMEA, APAC)"), "")
    assert f["remote_regions"] == ["EMEA", "APAC"]
    f = derive_facts(_job("Dev", "Worldwide", is_remote=True), "")
    assert f["remote_regions"] == ["WORLDWIDE"]
    f = derive_facts(_job("Dev", "Remote", is_remote=True), "")
    assert f["remote_regions"] == [] and f["country_codes"] == []
    f = derive_facts(_job("Dev", "LATAM"), "")
    assert f["remote_regions"] == []  # not remote: regions only describe remote jobs


def test_resolve_place():
    assert resolve_place("Bangalore") == ("IN", "bengaluru")
    assert resolve_place("Gurgaon") == ("IN", "gurugram")
    assert resolve_place("India") == ("IN", None)
    assert resolve_place("USA") == ("US", None)
    assert resolve_place("UK") == ("GB", None)
    assert resolve_place("de") == ("DE", None)
    assert resolve_place("New York, NY") == ("US", "new york")
    assert resolve_place("Atlantis") == (None, None)


def test_location_match():
    lm = location_match
    assert lm([], [], [], None, None) is True
    # onsite / hybrid
    assert lm(["India"], ["IN"], [], "onsite", "Pune, India") is True
    assert lm(["Bengaluru"], ["IN"], [], "hybrid", "Bangalore, Karnataka") is True
    assert lm(["Bengaluru"], ["IN"], [], "onsite", "Mumbai, India") is False
    assert lm(["Bengaluru"], ["IN"], [], "onsite", "India") is None
    assert lm(["India"], ["US"], [], "onsite", "Austin, TX") is False
    assert lm(["India"], [], [], None, None) is None
    assert lm(["Atlantis"], ["US"], [], "onsite", "Austin, TX") is None
    # remote
    assert lm(["India"], [], [], "remote", "Remote") is True
    assert lm(["India"], [], ["WORLDWIDE"], "remote", "Anywhere") is True
    assert lm(["India"], ["US"], ["US"], "remote", "Remote (US only)") is False
    assert lm(["India"], [], ["APAC"], "remote", "Remote - APAC") is True
    assert lm(["Germany"], [], ["EU"], "remote", "Remote - Europe") is True
    assert lm(["Berlin"], [], ["EMEA"], "remote", "Remote EMEA") is True
    assert lm(["EU"], [], ["EMEA"], "remote", "Remote EMEA") is True
