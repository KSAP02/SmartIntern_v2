"""Skills vocabulary: spot named skills in job text (no LLM, no network).

The bundled list lives in `data/skills_vocab.txt` (one canonical name per line, aliases
after "|", "=" marks a case-sensitive alias). The user's own skill items can be added per
call (`extra_terms`), so a job can be checked for skills you have and skills you lack.

Ambiguous words get special rules instead of plain matching (precision over recall):
- Go: "golang", or a capitalised "Go" in a list-like context ("Python, Go", "in Go").
- R: a capitalised "R" in a list-like context, or "R programming"/"R language"/"RStudio".
- C: only "C/C++", "C, C++", "C programming", "C language", "ANSI C", "Embedded C".
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

_VOCAB_FILE = Path(__file__).parent / "data" / "skills_vocab.txt"

# Characters that may not touch a term on either side (so "java" != "javascript").
_LEFT_EDGE = r"(?<![A-Za-z0-9_+#])"
_RIGHT_EDGE = r"(?![A-Za-z0-9_+#])"

_SPECIAL = {"go", "golang", "r", "c"}


def _key(s: str) -> str:
    """Lookup key: lowercase, no spaces or hyphens ("Machine-Learning" -> "machinelearning")."""
    return re.sub(r"[\s\-]+", "", s.strip().lower())


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, str], tuple[tuple[str, bool], ...]]:
    """Returns (key -> canonical, ((alias, case_sensitive), ...))."""
    alias_to_canon: dict[str, str] = {}
    aliases: list[tuple[str, bool]] = []
    for raw in _VOCAB_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        canon = parts[0].lstrip("=").lower()
        for p in parts:
            cs = p.startswith("=")
            term = p[1:] if cs else p
            alias_to_canon.setdefault(_key(term), canon)
            aliases.append((term, cs))
    return alias_to_canon, tuple(aliases)


def vocabulary() -> list[str]:
    """All canonical skill names (sorted)."""
    return sorted(set(_load()[0].values()) | {"go", "r", "c"})


def normalize_skill(s: str) -> str:
    """Canonical form if known (via aliases), else lowercase trimmed."""
    clean = re.sub(r"\s+", " ", (s or "").strip()).lower()
    k = _key(clean)
    if k in ("go", "golang"):
        return "go"
    if k in ("r", "rlang", "rprogramming", "rlanguage"):
        return "r"
    if k in ("c", "clanguage", "cprogramming", "ansic"):
        return "c"
    return _load()[0].get(k, clean)


def _term_regex(term: str) -> str:
    out = []
    for ch in term:
        if ch == " ":
            out.append(r"[\s\-]+")
        elif ch == "-":
            out.append(r"[\s\-]?")
        else:
            out.append(re.escape(ch))
    return "".join(out)


@lru_cache(maxsize=64)
def _compiled(extra: tuple[str, ...]) -> tuple[re.Pattern[str], dict[str, str]]:
    alias_to_canon, aliases = _load()
    lookup = dict(alias_to_canon)
    terms: list[tuple[str, bool]] = list(aliases)
    for t in extra:
        canon = normalize_skill(t)
        if _key(canon) in _SPECIAL or _key(t) in _SPECIAL:
            continue
        clean = re.sub(r"\s+", " ", t.strip())
        if len(clean) < 2 or len(clean) > 40 or len(clean.split()) > 4:
            continue
        lookup.setdefault(_key(clean), canon)
        lookup.setdefault(_key(canon), canon)
        terms.append((clean, False))
        if canon != clean.lower():
            terms.append((canon, False))
    # Longest first so "react native" wins over "react" at the same position.
    seen: set[tuple[str, bool]] = set()
    alts: list[tuple[int, str]] = []
    for term, cs in terms:
        sig = (term if cs else term.lower(), cs)
        if sig in seen:
            continue
        seen.add(sig)
        body = _term_regex(term)
        alts.append((len(term), f"(?-i:{body})" if cs else body))
    alts.sort(key=lambda a: -a[0])
    pattern = _LEFT_EDGE + "(?:" + "|".join(a[1] for a in alts) + ")" + _RIGHT_EDGE
    return re.compile(pattern, re.IGNORECASE), lookup


# ── Special cases: Go, R, C ────────────────────────────────────────────────────

_LIST_BEFORE = re.compile(
    r"(?:^|[,/(;&:|]|^\s*[-*•·]|\b(?:in|with|and|or|using|like|of|e\.g\.|including|incl\.|especially|as)\s*)\s*$"
)
_LIST_AFTER = re.compile(r"^(?:[ \t]*(?:\n|$)|\s*(?:[,/);&|]|\.(?:\s|$)|\s(?:and|or)\b))")
_GO_WORD = re.compile(r"(?<![A-Za-z0-9_\-])Go(?![A-Za-z0-9_+#'’\-])")
_GOLANG = re.compile(r"\bgolang\b", re.IGNORECASE)
_R_WORD = re.compile(r"(?<![A-Za-z0-9_\-&.'’])R(?![A-Za-z0-9_+#&'’\-])")
_R_PHRASE = re.compile(r"(?<![A-Za-z0-9])R(?=\s+(?:programming|language|studio)\b)|\bRStudio\b")
_C_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9_+#.\-/])C(?=\s*(?:/|,|and|or)\s*C\+\+)"),
    re.compile(r"(?<![A-Za-z0-9_+#.\-/])C(?=\s+(?:programming|language)\b)"),
    re.compile(r"\b(?:ANSI|ansi)\s+C(?![A-Za-z0-9_+#])"),
]


def _context_ok(text: str, start: int, end: int) -> bool:
    """True if the word at [start, end) sits in a list-like spot ("Python, Go", "in Go")."""
    line_before = text[text.rfind("\n", 0, start) + 1 : start]
    if len(line_before) > 25:
        line_before = "\x00" + line_before[-25:]  # keeps "^" from matching mid-line
    after = text[end : end + 6]
    return bool(_LIST_BEFORE.search(line_before) and _LIST_AFTER.match(after))


def _special_hits(text: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for m in _GOLANG.finditer(text):
        hits.append((m.start(), "go"))
    for m in _GO_WORD.finditer(text):
        if _context_ok(text, m.start(), m.end()):
            hits.append((m.start(), "go"))
    for m in _R_PHRASE.finditer(text):
        hits.append((m.start(), "r"))
    for m in _R_WORD.finditer(text):
        if _context_ok(text, m.start(), m.end()):
            hits.append((m.start(), "r"))
    for pat in _C_PATTERNS:
        for m in pat.finditer(text):
            hits.append((m.start(), "c"))
    return hits


def find_skills(text: str, extra_terms: Iterable[str] = ()) -> list[str]:
    """Canonical skill names found in `text`, in order of first appearance, deduped.

    `extra_terms` are the user's own skill items, added to the vocabulary for this call
    and reported by their normalized form.
    """
    if not text:
        return []
    extra = tuple(sorted({t.strip() for t in extra_terms if t and t.strip()}))
    pattern, lookup = _compiled(extra)
    hits: list[tuple[int, str]] = []
    for m in pattern.finditer(text):
        canon = lookup.get(_key(m.group(0)))
        if canon:
            hits.append((m.start(), canon))
    hits.extend(_special_hits(text))
    hits.sort(key=lambda h: h[0])
    out: list[str] = []
    seen: set[str] = set()
    for _, canon in hits:
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out
