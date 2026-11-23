"""Shared plumbing for job sources: the source contract, one HTTP helper, errors, field helpers.

**Source contract (Phase 2.7).** A source is one module in this package exposing an adapter
object with `name`, `label`, `kind`, `quota`, `terms_url`, `env_keys` and `configured()`, listed
in `sources.SOURCES`. Search sources (kind "search") take a query and run inside the search plan
and request budget; board / feed / page sources return everything and are pre-checked (India
scope + title) before storing. Every adapter returns `NormalizedJob`s. Adding a source = one
file + one registry line + its config section.

Clients are read-only callers of documented APIs. They return `NormalizedJob`s and never
convert HTML to text (another module does that). Nothing about the user is sent beyond the
search terms they configured.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal, Protocol

import httpx

USER_AGENT = "SmartIntern/0.1 (personal job search)"  # generic on purpose: no name, no email

SourceKind = Literal["search", "board", "feed", "page"]


class SourceAdapter(Protocol):
    """What every job source exposes (see the module docstring)."""

    name: str  # registry key, also api_calls.api and jobs.seen_on[].source
    label: str  # shown to the user
    kind: SourceKind
    quota: bool  # metered: every request goes through api_budget
    terms_url: str | None
    env_keys: tuple[str, ...]  # keys it needs in .env (empty = none)

    def configured(self) -> bool: ...
MAX_RETRY_WAIT = 30.0  # seconds; caps Retry-After and backoff


class SourceError(RuntimeError):
    """A fetch failed; the message is short and readable by the user."""


class SourceHttp:
    """Sync HTTP client with retries (network errors, 429, 5xx) and Retry-After support."""

    def __init__(self, timeout: float = 20, max_retries: int = 3, transport: httpx.BaseTransport | None = None):
        self.max_retries = max(0, int(max_retries))
        self.label = "Source"  # adapters set this so errors name the source
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*;q=0.5"},
            transport=transport,
        )

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> Any:
        resp = self._get(url, params, headers)
        try:
            return resp.json()
        except ValueError as e:
            raise SourceError(f"{self.label}: response was not valid JSON") from e

    def get_text(self, url: str, params: dict | None = None) -> str:
        return self._get(url, params).text

    def get_bytes(self, url: str, headers: dict | None = None) -> bytes:
        """Raw bytes (e.g. one byte range of a large file: headers={"Range": "bytes=a-b"})."""
        return self._get(url, None, headers).content

    def size(self, url: str) -> int:
        """A file's size in bytes, from a one-byte range request ("Content-Range: bytes 0-0/<size>")."""
        resp = self._get(url, None, {"Range": "bytes=0-0"})
        total = (resp.headers.get("Content-Range") or "").rpartition("/")[2]
        if not total.isdigit():
            raise SourceError(f"{self.label}: the server didn't say how large the file is")
        return int(total)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SourceHttp:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, url: str, params: dict | None, headers: dict | None = None) -> httpx.Response:
        tries = self.max_retries + 1
        for attempt in range(1, tries + 1):
            wait: float | None
            try:
                resp = self._client.get(url, params=params, headers=headers)
            except httpx.TimeoutException as e:
                problem, wait = "timed out", _backoff(attempt)
                cause: Exception | None = e
            except httpx.TransportError as e:
                problem, wait = "network error", _backoff(attempt)
                cause = e
            else:
                code = resp.status_code
                if code < 400:
                    return resp
                why = _error_message(resp)
                if code == 404:
                    raise SourceError(f"{self.label}: not found (HTTP 404){why}")
                if code != 429 and code < 500:
                    raise SourceError(f"{self.label}: HTTP {code}{why}")
                problem, cause = f"HTTP {code}", None
                wait = _retry_after(resp.headers.get("Retry-After"))
                if wait is None:
                    wait = _backoff(attempt)
            if attempt == tries:
                suffix = "" if tries == 1 else f" after {tries} tries"
                raise SourceError(f"{self.label}: {problem}{suffix}") from cause
            time.sleep(min(wait, MAX_RETRY_WAIT))
        raise AssertionError("unreachable")


def _error_message(resp: httpx.Response) -> str:
    """The API's own short explanation, if it sent one as JSON ({"error": {"message": ...}} or
    {"message": ...}), formatted as ": <message>". Never echoes request headers."""
    try:
        data = resp.json()
    except ValueError:
        return ""
    msg = None
    if isinstance(data, dict):
        err = data.get("error")
        msg = (err.get("message") if isinstance(err, dict) else err) or data.get("message")
    return f": {str(msg)[:160]}" if isinstance(msg, str) and msg.strip() else ""


def _backoff(attempt: int) -> float:
    return min(2.0 ** (attempt - 1), MAX_RETRY_WAIT)  # 1, 2, 4, ...


def _retry_after(value: str | None) -> float | None:
    """Seconds to wait from a Retry-After header (delta-seconds or HTTP date)."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


# ── Small mapping helpers shared by adapters ──────────────────────────────────


def parse_datetime(value: Any) -> datetime | None:
    """ISO 8601 string or unix seconds/milliseconds -> aware UTC datetime. Naive = UTC."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
            n = float(value)
            if n > 1e11:  # milliseconds
                n /= 1000
            return datetime.fromtimestamp(n, tz=UTC)
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def clean_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for v in value:
        s = clean_str(v)
        if s and s not in out:
            out.append(s)
    return out


def positive_number(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None
