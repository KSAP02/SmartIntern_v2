"""Job text helpers (no LLM, no network): HTML -> text, requirement chunks, identity keys.

Pure functions used by the scan pipeline (plan §3 dedupe, §4 steps ③ and ⑤):
- `html_to_text` / `job_plain_text`: readable plain text that keeps headings and bullets.
- `chunk_requirements`: one chunk per bullet or sentence, tagged with the heading it sits
  under (requirements / nice_to_have / responsibilities / benefits / about / other).
- `normalize_company`, `normalize_title`, `dedupe_key`, `canonical_url`, `content_hash`:
  cross-source identity and change detection.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.job_schemas import NormalizedJob

# ── HTML -> text ───────────────────────────────────────────────────────────────

_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "main", "aside", "nav",
    "ul", "ol", "dl", "dt", "dd", "table", "thead", "tbody", "tr", "blockquote", "pre",
    "figure", "figcaption", "form", "fieldset", "address", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BOLD_TAGS = {"strong", "b"}
_DROP_TAGS = ["script", "style", "noscript", "template", "head", "svg", "iframe"]
_INLINE_WS = re.compile(r"[ \t\r\f\v  -​  　]+")
_LOOKS_HTML = re.compile(r"<(?:p|div|br|li|ul|ol|h[1-6]|strong|b|span|em|a)\b[^>]*>", re.IGNORECASE)


def _is_blank_node(node) -> bool:
    from bs4 import NavigableString

    if node is None:
        return True
    if isinstance(node, NavigableString):
        return not str(node).strip()
    return getattr(node, "name", None) == "br"


def _ends_line(node, forward: bool) -> bool:
    """True if, walking from `node` in one direction, we hit a line break before any text."""
    from bs4 import NavigableString

    sib = node.next_sibling if forward else node.previous_sibling
    while sib is not None:
        if isinstance(sib, NavigableString):
            if str(sib).strip():
                return False
        elif sib.name == "br" or sib.name in _BLOCK_TAGS or sib.name == "li":
            return True
        elif sib.get_text(strip=True):
            return False
        sib = sib.next_sibling if forward else sib.previous_sibling
    parent = node.parent
    if parent is None or parent.name in _BLOCK_TAGS or parent.name in ("li", "body", "[document]"):
        return True
    return _ends_line(parent, forward)


def _mark_heading(tag) -> None:
    """Puts a heading on its own line and ends it with ':' so the chunker can see it."""
    text = tag.get_text(" ", strip=True)
    if not text or len(text) > 120:
        return
    if text[-1] not in ":.?!":
        tag.append(":")
    tag.insert_before("\n\n")
    tag.insert_after("\n")


def html_to_text(html: str) -> str:
    """HTML -> plain text that keeps structure: headings on their own line (ending in ':'),
    `<li>` as "- item", block elements and `<br>` as line breaks, at most 2 blank lines."""
    if not html or not html.strip():
        return ""
    from bs4 import BeautifulSoup

    from bs4 import Comment

    soup = BeautifulSoup(html, "html.parser")
    for t in soup.find_all(_DROP_TAGS):
        t.decompose()
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    # Source newlines inside HTML are just spaces; line breaks come from the tags below.
    for s in soup.find_all(string=True):
        if s.find_parent("pre") is None and re.search(r"\s", s):
            s.replace_with(re.sub(r"\s+", " ", str(s)))

    for tag in soup.find_all(list(_HEADING_TAGS)):
        _mark_heading(tag)
    for tag in soup.find_all(list(_BOLD_TAGS)):
        if tag.find_parent("li") or tag.find_parent(list(_HEADING_TAGS)):
            continue
        text = tag.get_text(" ", strip=True)
        if text and len(text) <= 80 and _ends_line(tag, False) and _ends_line(tag, True):
            _mark_heading(tag)

    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert(0, "\n- ")
        li.append("\n")
    for tag in soup.find_all(list(_BLOCK_TAGS - _HEADING_TAGS)):
        tag.insert_before("\n")
        tag.append("\n")
    for cell in soup.find_all(["td", "th"]):
        cell.append(" ")

    return _clean_text(soup.get_text())


def _clean_text(text: str) -> str:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _INLINE_WS.sub(" ", raw).strip()
        if lines and lines[-1] in ("-", "- -") and line:
            lines[-1] = "- " + (line[2:] if line.startswith("- ") else line)
            continue
        lines.append(line)
    out: list[str] = []
    blanks = 0
    for line in lines:
        if line in ("-", "- -"):
            continue
        if not line:
            blanks += 1
            if blanks > 2 or not out:
                continue
        else:
            blanks = 0
        out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def job_plain_text(job: NormalizedJob) -> str:
    """The job's description as plain text: description_text, else converted HTML, else ""."""
    if job.description_text and job.description_text.strip():
        text = job.description_text
        return html_to_text(text) if _LOOKS_HTML.search(text) else _clean_text(text)
    if job.description_html and job.description_html.strip():
        return html_to_text(job.description_html)
    return ""


# ── Requirement chunks ─────────────────────────────────────────────────────────


@dataclass
class Chunk:
    section: str  # requirements | responsibilities | nice_to_have | about | benefits | other
    importance: str  # must | nice | unknown
    text: str  # one bullet or sentence, cleaned, 15–400 chars
    position: int


_MIN_CHUNK, _MAX_CHUNK = 15, 400

# Heading phrases per section. Checked in this order (first hit wins), against the heading
# normalised to lowercase words. "contains" phrases may appear anywhere in a short heading.
_HEADING_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("other", re.compile(
        r"\b(?:equal (?:employment )?opportunit|eeo\b|diversity|inclusion|accommodation|privacy|"
        r"how to apply|application process|interview process|hiring process|recruitment process|"
        r"additional information|disclaimer|legal|e verify|logistics)")),
    ("nice_to_have", re.compile(
        r"\b(?:nice to haves?|good to haves?|nice ?to ?have|preferred|bonus|plus(?:es)?\b|"
        r"would be (?:great|nice|awesome|a plus)|desir(?:ed|able)|extra credit|ideally)")),
    ("requirements", re.compile(r"^about you\b")),
    ("responsibilities", re.compile(
        r"^about (?:the|this) (?:role|job|position|opportunity|internship|team you ll join)\b")),
    ("about", re.compile(
        r"^(?:about\b|who we are|our (?:mission|story|company|culture|values|vision|team)\b|"
        r"company (?:overview|description|profile)|the company\b|life at\b|why (?:we exist|us)\b)")),
    ("benefits", re.compile(
        r"\b(?:benefits|perks|what we offer|we offer|what s in it for you|what you ll get|"
        r"what you get|why join|why work|why you ll love|compensation|salary|stipend|"
        r"rewards|our offer|pay and|what you ll learn|what you will learn|you ll learn|"
        r"learning opportunit(?:y|ies))\b")),
    ("requirements", re.compile(
        r"\b(?:requirements?|qualifications?|what you ll need|what you need|what we re looking for|"
        r"(?:what|who) we (?:re|are) looking for|^(?:we re |we are )?looking for$|who you are|"
        r"must haves?|^you have$|what you have|you ll have|you should have|what you bring|"
        r"you ll bring|you bring|"
        r"what we need|eligibility|who can apply|ideal candidate|candidate profile|"
        r"desired profile|your profile|your background|your skills|skills|experience|education|"
        r"competenc(?:y|ies)|key skills|technical skills|prerequisites|knowledge)\b")),
    ("responsibilities", re.compile(
        r"\b(?:responsibilit(?:y|ies)|what you ll do|what you will do|what you ll be doing|"
        r"what you will be doing|what you ll work on|the role|your role|role overview|"
        r"day to day|in this role|duties|your impact|the impact you ll have|your mission|"
        r"the opportunity|the job|role description|job description|job summary|role summary|"
        r"what the job involves|key tasks|tasks|^you will$|^you ll$)\b")),
]

# A line without a colon is only a heading if it is short and has no sentence-ending period.
_GENERIC_ONLY = re.compile(
    r"^(?:(?:required|key|technical|core|desired|necessary|relevant|your|the|basic|minimum|"
    r"general|job|role|main|primary|additional|our)\s+)*"
    r"(?:skills?|experience|education|qualifications?|requirements?|knowledge|competenc(?:y|ies)|"
    r"responsibilit(?:y|ies)|duties|tasks|benefits|perks|compensation|eligibility|prerequisites|"
    r"roles?)"
    r"(?:\s+(?:and|or)\s+(?:\w+\s+)?(?:skills?|experience|education|qualifications?|requirements?|"
    r"knowledge|abilities|competenc(?:y|ies)|responsibilit(?:y|ies)|duties|benefits|perks|"
    r"compensation|attributes))*"
    r"(?:\s+(?:required|needed|needs|preferred|overview|summary))?$"
)
_GENERIC_WORDS = re.compile(
    r"\b(?:skills?|experience|education|qualifications?|requirements?|knowledge|competenc(?:y|ies)|"
    r"responsibilit(?:y|ies)|duties|tasks|benefits|perks|compensation|eligibility|prerequisites)\b"
)
_BULLET = re.compile(r"^\s*(?:[-*•·–—▪◦●○■□➢►▶✓✔→>]+|\(?\d{1,2}[.)]|\(?[a-z][.)])\s+")
_MD_HEADING = re.compile(r"^\s*#{1,6}\s+")
_EEO = re.compile(
    r"equal (?:employment )?opportunit|without regard to|regardless of (?:race|gender|age|religion|sex)|"
    r"reasonable accommodation|protected veteran|e-verify|affirmative action|national origin|"
    r"sexual orientation|gender identity|privacy (?:policy|notice)|applicant privacy|"
    r"unsolicited (?:resumes|applications)|recruitment agenc|fraudulent (?:job|recruit|offer)|"
    r"we celebrate diversity|committed to (?:creating )?(?:a )?divers|"
    r"fair chance|encourage you to apply even if|meet every (?:single )?qualification|"
    r"underrepresented groups|imposter syndrome|find (?:more )?(?:[\w-]+ ){0,4}jobs in .{1,60} on arbeitnow|"
    r"compensation range for this role|on target earnings",
    re.IGNORECASE,
)
_NICE_WORDS = re.compile(
    r"\b(?:nice[ -]to[ -]have|good[ -]to[ -]have|preferred|preferably|bonus|a (?:big |huge )?plus|"
    r"ideally|desirable|is an advantage|would be an advantage)\b",
    re.IGNORECASE,
)
_MUST_WORDS = re.compile(r"\b(?:required|requires|must|mandatory|minimum|essential)\b", re.IGNORECASE)
_REQ_LIKE = re.compile(
    r"\b(?:\d+\+?\s*(?:years?|yrs)|experience (?:with|in|of)|proficien|knowledge of|"
    r"familiar(?:ity)? with|understanding of|degree in|bachelor|master'?s|b\.?\s?tech|"
    r"pursuing|skills? in|hands-on|strong (?:grasp|background|command))",
    re.IGNORECASE,
)
_ABBREV = re.compile(
    r"(?:\b(?:e\.g|i\.e|etc|vs|incl|approx|esp|resp|dept|mr|mrs|ms|dr|sr|jr|st|no|inc|ltd|co|corp|"
    r"u\.s|u\.k|a\.m|p\.m|fig|min|max|yrs?|mos?|ph\.d|b\.tech|m\.tech|b\.sc|m\.sc|b\.e|m\.e)\.)$",
    re.IGNORECASE,
)
_SENT_SPLIT = re.compile(r"(?<=[.!?])[\"”’)]?\s+(?=[A-Z0-9\"“(])")


def _norm_heading(line: str) -> str:
    h = _MD_HEADING.sub("", line).strip()
    h = h.strip("*_ ").strip()
    h = h.replace("’", "'").replace("&", " and ").lower()
    h = re.sub(r"[^a-z0-9' ]+", " ", h)
    h = h.replace("'", " ")
    return re.sub(r"\s+", " ", h).strip()


def _section_for(heading: str) -> str | None:
    for section, pat in _HEADING_RULES:
        if pat.search(heading):
            return section
    return None


def _heading(line: str) -> tuple[bool, str | None]:
    """(is_heading, section). section None = heading we don't recognise."""
    if _BULLET.match(line):
        return False, None
    raw = _MD_HEADING.sub("", line).strip()
    md = bool(_MD_HEADING.match(line)) or (raw.startswith("**") and raw.rstrip(":").endswith("**"))
    body = raw.strip("*_ ").strip()
    if not body or len(body) > 80:
        return False, None
    colon = body.endswith(":")
    if not colon and body[-1:] in ".;,":
        return False, None
    h = _norm_heading(body)
    if not h:
        return False, None
    words = h.split()
    section = _section_for(h)
    if colon or md:
        return (True, section) if len(words) <= 10 else (False, None)
    if body.endswith("?") and len(words) <= 8:
        return (section is not None), section
    if len(words) > 8 or section is None:
        return False, None
    # Plain short line: a generic word ("skills") only counts if the line is just a heading.
    if _GENERIC_WORDS.search(h) and not _GENERIC_ONLY.match(h):
        distinctive = re.sub(_GENERIC_WORDS, "", h)
        hit = any(pat.search(distinctive) for s, pat in _HEADING_RULES if s == section)
        if not hit:
            return False, None
    return True, section


def _inline_heading(line: str) -> tuple[str | None, str]:
    """"Requirements: Python, SQL" -> ("requirements", "Python, SQL")."""
    if _BULLET.match(line):
        return None, line
    m = re.match(r"^\**([A-Za-z][^:]{2,40}?)\**\s*:\s*\**\s*(.{15,})$", line)
    if not m:
        return None, line
    h = _norm_heading(m.group(1))
    if len(h.split()) > 6:
        return None, line
    section = _section_for(h)
    if section in ("requirements", "nice_to_have", "responsibilities", "benefits", "about"):
        if section in ("requirements", "responsibilities") and not (
            _GENERIC_ONLY.match(h) or _section_for(re.sub(_GENERIC_WORDS, "", h))
        ):
            return None, line
        return section, m.group(2).strip()
    return None, line


def _sentences(text: str) -> list[str]:
    parts = _SENT_SPLIT.split(text)
    out: list[str] = []
    for p in parts:
        if out and _ABBREV.search(out[-1]):
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return [p.strip() for p in out if p.strip()]


def _clean_chunk(text: str) -> str:
    t = _BULLET.sub("", text).strip()
    t = t.strip("*_ ").strip()
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\s+", " ", t)
    if len(t) > _MAX_CHUNK:
        cut = t[:_MAX_CHUNK]
        sp = cut.rfind(" ")
        t = (cut[:sp] if sp > _MAX_CHUNK * 0.6 else cut).rstrip(" ,;:") + "…"
    return t


def _importance(section: str, text: str) -> str:
    base = {"requirements": "must", "nice_to_have": "nice"}.get(section, "unknown")
    if section in ("benefits", "other"):
        return base
    if _NICE_WORDS.search(text):
        return "nice"
    if _MUST_WORDS.search(text):
        return "must"
    return base


_HIGHLIGHT_SECTIONS = {"Qualifications": "requirements", "Responsibilities": "responsibilities"}


def chunks_from_highlights(highlights: dict | None, max_chunks: int = 60) -> list[Chunk]:
    """The source's own lists (JSearch job_highlights) as chunks: Qualifications -> requirements,
    Responsibilities -> responsibilities. Benefits are skipped. [] when there is nothing usable."""
    chunks: list[Chunk] = []
    for key, section in _HIGHLIGHT_SECTIONS.items():
        for item in (highlights or {}).get(key) or []:
            t = _clean_chunk(str(item))
            if len(t) < _MIN_CHUNK or len(chunks) >= max_chunks:
                continue
            if _EEO.search(t):
                chunks.append(Chunk("other", "unknown", t, len(chunks)))
                continue
            chunks.append(Chunk(section, _importance(section, t), t, len(chunks)))
    return chunks


def chunk_requirements(text: str, max_chunks: int = 60) -> list[Chunk]:
    """Split a job description into chunks (one per bullet or sentence) tagged by section."""
    chunks: list[Chunk] = []
    section: str | None = None  # None = before any heading

    def add(piece: str, sec: str, inferred: bool = False) -> None:
        t = _clean_chunk(piece)
        if len(t) < _MIN_CHUNK or len(chunks) >= max_chunks:
            return
        if _EEO.search(t):
            chunks.append(Chunk("other", "unknown", t, len(chunks)))
            return
        imp = _importance(sec, t)
        if inferred and sec == "requirements" and imp == "must" and not _MUST_WORDS.search(t):
            imp = "unknown"  # guessed section: don't claim it's a must-have
        chunks.append(Chunk(sec, imp, t, len(chunks)))

    for raw in (text or "").split("\n"):
        if len(chunks) >= max_chunks:
            break
        line = raw.strip()
        if not line:
            continue
        # "Stipend: INR 20,000 per month" carries content: check the inline form first, so a
        # line that merely starts with a heading word isn't swallowed as a bare heading.
        inline_sec, rest = _inline_heading(line)
        if inline_sec and section == "other":
            # Inside a legal / process / logistics block, "Minimum education: ..." or
            # "Visa sponsorship: ..." are company boilerplate, not this job's requirements.
            inline_sec, rest = None, line
            current = "other"
            for sent in _sentences(line):
                add(sent, current)
            continue
        if not inline_sec:
            is_head, sec = _heading(line)
            if is_head:
                if sec or section is not None:
                    section = sec or "other"
                continue
        current = section
        if inline_sec:
            line = rest
            current = inline_sec
            # "Requirements: you should have:" introduces a list -> opens the section.
            # "Minimum education: Bachelor's degree" is one labelled line -> applies to it only.
            if inline_sec in ("requirements", "nice_to_have", "responsibilities") and rest.endswith(":"):
                section = inline_sec
        is_bullet = bool(_BULLET.match(line))
        inferred = False
        if current is None:
            if is_bullet and _REQ_LIKE.search(line):
                current, inferred = "requirements", True
            else:
                current = "about"
        if is_bullet:
            body = _BULLET.sub("", line)
            if len(body) <= _MAX_CHUNK:
                add(body, current, inferred)
                continue
            line = body
        for sent in _sentences(line):
            add(sent, current, inferred)
    return chunks


# ── Identity keys ──────────────────────────────────────────────────────────────

_LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "llp", "lp", "ltd", "limited", "pvt", "private", "plc",
    "gmbh", "ag", "corp", "corporation", "co", "company", "sa", "sas", "sarl", "bv", "nv",
    "pte", "pty", "srl", "spa", "oy", "ab", "kk", "ug", "se", "lda", "sl",
}


def normalize_company(name: str | None) -> str:
    """"Acme Technologies Pvt. Ltd." -> "acme technologies"; "" if unknown."""
    if not name:
        return ""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    words = s.split()
    while len(words) > 1 and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def normalize_title(title: str) -> str:
    """"Software Engineer (m/f/d) - Backend" -> "software engineer backend"."""
    s = (title or "").lower()
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}", " ", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w\s+#]", " ", s)
    words = [{"sr": "senior", "jr": "junior"}.get(w, w) for w in s.split()]
    return " ".join(words)


_REMOTE_LOC = re.compile(r"\b(?:remote|anywhere|worldwide|work from home|wfh)\b", re.IGNORECASE)
_CITY_ALIASES = {
    "bangalore": "bengaluru", "gurgaon": "gurugram", "bombay": "mumbai", "new delhi": "delhi",
    "madras": "chennai", "calcutta": "kolkata", "nyc": "new york", "new york city": "new york",
    "sf": "san francisco", "munchen": "munich", "münchen": "munich", "zürich": "zurich",
}


def _normalize_location(location: str | None) -> str:
    if not location:
        return ""
    if _REMOTE_LOC.search(location):
        return "remote"
    first = re.split(r"[,;/|(]| - ", location.lower())[0]
    first = re.sub(r"[^\w\s]", " ", first)
    first = re.sub(r"\s+", " ", first).strip()
    return _CITY_ALIASES.get(first, first)


def dedupe_key(company: str | None, title: str, location: str | None) -> str:
    """"company|title|location", each normalised (location loosely: "Remote (US)" -> "remote")."""
    return f"{normalize_company(company)}|{normalize_title(title)}|{_normalize_location(location)}"


_TRACKING_PARAMS = {
    "gh_src", "source", "src", "ref", "referrer", "referer", "lever-origin", "lever-source",
    "lever-source[]", "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "_hsenc",
    "_hsmi", "trk", "trkinfo", "trackingid", "refid", "ref_id", "campaign", "medium",
    "shared_from", "via", "jobsource", "jobboard", "iis",
    "iisn", "ccuid", "utm",
}


def canonical_url(url: str | None) -> str | None:
    """Lowercase scheme/host, https, no "www.", no tracking params, no fragment or trailing slash."""
    if not url or not url.strip():
        return None
    u = url.strip()
    try:
        parts = urlsplit(u)
    except ValueError:
        return u
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return u
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(":443") or host.endswith(":80"):
        host = host.rsplit(":", 1)[0]
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    query.sort()
    path = parts.path.rstrip("/")
    return urlunsplit(("https", host, path, urlencode(query), ""))


def content_hash(title: str, text: str) -> str:
    """sha256 hex of the normalised title + whitespace-collapsed text (change detection)."""
    body = re.sub(r"\s+", " ", text or "").strip()
    return hashlib.sha256(f"{normalize_title(title)}\n{body}".encode("utf-8")).hexdigest()


# ── Job titles vs your roles ───────────────────────────────────────────────────

# Short forms the embedding model confuses ("ML Engineer" ~ "Mechanical Engineer"): compare the
# expanded words instead.
TITLE_ABBREVIATIONS = {
    "ml": "machine learning", "ai": "artificial intelligence", "llm": "large language model",
    "llms": "large language models", "nlp": "natural language processing", "cv": "computer vision",
    "sde": "software development engineer", "swe": "software engineer", "mle": "machine learning engineer",
    "genai": "generative artificial intelligence", "qa": "quality assurance", "ui": "user interface",
    "ux": "user experience", "devops": "devops", "fe": "frontend", "be": "backend",
}
# Words that say nothing about the role (level, place, urgency): dropped before comparing.
_TITLE_NOISE = re.compile(
    r"\b(?:fresher|freshers|entry[- ]level|junior|jr\.?|graduate|grad|trainee|urgent(?:ly)?|hiring|immediate|"
    r"joiner|remote|hybrid|on[- ]?site|wfh|work from home|india|bangalore|bengaluru|hyderabad|pune|mumbai|delhi|"
    r"chennai|noida|gurgaon|gurugram|kolkata|ahmedabad)\b|!+",
    re.IGNORECASE,
)


def expand_abbreviations(text: str) -> str:
    """"ML Engineer" -> "machine learning Engineer" (whole words only)."""
    return re.sub(r"\b[A-Za-z]+\b", lambda m: TITLE_ABBREVIATIONS.get(m.group(0).lower(), m.group(0)), text)


def title_variants(title: str) -> list[str]:
    """What to compare with your roles: the whole title and each part of it (split on " - ", "|",
    brackets, commas, " in "), minus level / place noise, each also with abbreviations expanded.
    "Entry-Level Machine Learning Engineer (LLM & AI Agent Specialist)" -> "Machine Learning
    Engineer", "LLM & AI Agent Specialist", ... so a long title isn't judged as one blur."""
    parts = re.split(r"\s+[-–—|:]\s+|[|()\[\],/]|\s+in\s+", title or "")
    out: list[str] = []
    for p in [title or "", *parts]:
        p = re.sub(r"\s{2,}", " ", _TITLE_NOISE.sub(" ", p)).strip(" -–—&.")
        if len(p) >= 3 and re.search(r"[A-Za-z]", p):
            for v in (p, expand_abbreviations(p)):
                if v not in out:
                    out.append(v)
    return out or [(title or "untitled").strip() or "untitled"]

