"""THE ONLY place model clients are built and called (chat + embeddings).

Everything else calls `chat_structured(task=...)` / `embed(...)`. Which model, temperature
and reasoning effort a task uses comes from settings/config.toml, never from call sites.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel

from backend.config import get_settings, get_tuning

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

OLLAMA_DEFAULT_URL = "http://localhost:11434/v1"


class ModelConfigError(RuntimeError):
    """Model settings, key or package missing. The message says how to fix it."""


class UpstreamError(RuntimeError):
    """The model provider returned an error or could not be reached."""


# ── Clients ────────────────────────────────────────────────────────────────────


@lru_cache(maxsize=8)
def _openai_client(api_key: str, base_url: str | None, timeout: float, retries: int, provider: str):
    """Cached per settings, so an Admin settings change (timeout, provider...) takes effect at once."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ModelConfigError("Package 'openai' missing. Add it to requirements.txt and rebuild.") from e
    if not api_key and base_url is None:
        raise ModelConfigError(f"LLM_API_KEY is not set for provider '{provider}'. Add it to the root .env.")
    return OpenAI(api_key=api_key or "none", base_url=base_url, timeout=timeout, max_retries=retries)


def get_client():
    """Chat client for the configured provider."""
    s, llm = get_settings(), get_tuning().llm
    provider = llm.provider.strip().lower()
    if not provider:
        raise ModelConfigError("[llm] provider is not set in settings/config.toml.")
    if not llm.model:
        raise ModelConfigError("[llm] model is not set in settings/config.toml.")
    if provider in ("openai", "ollama") or s.llm_base_url:
        base_url = s.llm_base_url or (OLLAMA_DEFAULT_URL if provider == "ollama" else None)
        return _openai_client(s.llm_api_key, base_url, llm.timeout_seconds, llm.max_retries, provider)
    raise ModelConfigError(f"Unsupported [llm] provider '{llm.provider}'. Add a branch for it in backend/model.py.")


def get_embed_client():
    s, emb = get_settings(), get_tuning().embedding
    provider = emb.provider.strip().lower()
    if provider != "openai":
        raise ModelConfigError(f"Unsupported [embedding] provider '{emb.provider}'. Add a branch in backend/model.py.")
    if not emb.model:
        raise ModelConfigError("[embedding] model is not set in settings/config.toml.")
    api_key = s.embedding_api_key or s.llm_api_key
    base_url = s.embedding_base_url or s.llm_base_url or None
    if not api_key:
        raise ModelConfigError("No OpenAI key for embeddings. Set LLM_API_KEY (or EMBEDDING_API_KEY) in the root .env.")
    return _openai_client(api_key, base_url, 60, 2, provider)


def _upstream(e: Exception) -> UpstreamError:
    msg = getattr(e, "message", None) or str(e)
    return UpstreamError(f"Model provider error ({e.__class__.__name__}): {msg}"[:500])


# ── Chat with structured output ────────────────────────────────────────────────

# Models that rejected a parameter; we stop sending it to them.
_unsupported: dict[str, set[str]] = {}


def chat_structured(task: str, system: str, user: str, schema: type[T]) -> T:
    """Run one LLM call for `task` and parse the reply into `schema` (OpenAI Responses API)."""
    import openai

    p = get_tuning().llm.for_task(task)
    client = get_client()
    params: dict = {"model": p.model, "max_output_tokens": p.max_output_tokens}
    reasoning = (p.reasoning_effort or "").strip().lower()
    if reasoning:
        params["reasoning"] = {"effort": reasoning}
    # Reasoning models usually reject temperature unless reasoning is off.
    if p.temperature is not None and reasoning in ("", "none"):
        params["temperature"] = p.temperature
    for name in _unsupported.get(p.model, set()):
        params.pop(name, None)

    for _ in range(3):
        try:
            resp = client.with_options(timeout=p.timeout_seconds).responses.parse(
                input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                text_format=schema,
                **params,
            )
            break
        except openai.BadRequestError as e:
            text = str(e).lower()
            dropped = next((k for k in ("temperature", "reasoning") if k in params and k in text), None)
            if not dropped:
                raise _upstream(e) from e
            log.warning("model %s rejected '%s'; retrying without it", p.model, dropped)
            _unsupported.setdefault(p.model, set()).add(dropped)
            params.pop(dropped)
        except openai.OpenAIError as e:
            raise _upstream(e) from e
    else:
        raise UpstreamError("Model call failed after removing unsupported parameters.")

    parsed = resp.output_parsed
    if parsed is None:
        raise UpstreamError("The model returned no structured output (it may have refused or run out of tokens).")
    return parsed


# ── Embeddings ─────────────────────────────────────────────────────────────────


def embed(texts: list[str]) -> list[list[float]]:
    import openai

    emb = get_tuning().embedding
    client = get_embed_client()
    out: list[list[float]] = []
    for i in range(0, len(texts), max(1, emb.batch_size)):
        batch = texts[i : i + emb.batch_size]
        try:
            resp = client.embeddings.create(model=emb.model, input=batch, dimensions=emb.dimensions)
        except openai.OpenAIError as e:
            raise _upstream(e) from e
        out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    return out


def embedding_signature() -> str:
    emb = get_tuning().embedding
    return f"{emb.provider}:{emb.model}:{emb.dimensions}"


# ── Status (no network calls) ──────────────────────────────────────────────────


def llm_status() -> dict:
    llm = get_tuning().llm
    try:
        get_client()
    except ModelConfigError as e:
        return {"configured": False, "detail": str(e)}
    return {"configured": True, "provider": llm.provider, "model": llm.model}


def embedding_status() -> dict:
    emb = get_tuning().embedding
    try:
        get_embed_client()
    except ModelConfigError as e:
        return {"configured": False, "detail": str(e)}
    return {"configured": True, "provider": emb.provider, "model": emb.model}
