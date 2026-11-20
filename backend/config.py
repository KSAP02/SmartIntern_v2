"""The ONLY module that reads configuration.

Two sources, two jobs:
- Environment / root .env  -> secrets + infrastructure (API keys, base URLs, data paths).
- settings/config.toml     -> tuning (models, temperature, reasoning effort, limits...).

Precedence: env var > config.toml > defaults here. Empty env values count as unset, so a
blank `LLM_MODEL=` in .env never wipes out the model chosen in config.toml.

config.toml is re-read whenever the file changes (hand edits apply within seconds, no
restart); a broken edit keeps the last good values and is reported by `tuning_error()`.
System -> Admin settings writes it through `write_tuning()`, which keeps every comment.
"""
from __future__ import annotations

import logging
import os
import threading
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Secrets and infrastructure, from the environment / root .env."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", env_ignore_empty=True)

    llm_api_key: str = ""
    llm_base_url: str = ""
    # Optional overrides of config.toml [llm] provider / model.
    llm_provider: str = ""
    llm_model: str = ""
    # Blank -> reuse llm_api_key / llm_base_url.
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    # Job source keys (blank -> that source is skipped and shows "API key missing").
    jsearch_api_key: str = ""

    data_dir: Path = ROOT / "data_warehouse" / "appdata"
    storage_backend: str = "local"
    # Blank -> <data_dir>/milvus.db (Milvus Lite).
    vector_db_uri: str = ""
    # Blank -> off. Where a read-only copy of app.db is kept fresh (Compose: data_warehouse/snapshots).
    snapshot_dir: Path | None = None
    config_file: Path = ROOT / "settings" / "config.toml"
    # Blank -> no CORS (the Node server / Vite proxy make the browser same-origin). Comma-separated
    # origins when the frontend calls the backend directly, e.g. https://smartintern.vercel.app
    cors_origins: str = ""


# ── Tuning (settings/config.toml) ──────────────────────────────────────────────


class LLMParams(BaseModel):
    provider: str = "openai"
    model: str = ""
    temperature: float | None = None
    reasoning_effort: str | None = None
    max_output_tokens: int = 4000
    timeout_seconds: float = 60
    max_retries: int = 2


class LLMConfig(LLMParams):
    tasks: dict[str, dict] = Field(default_factory=dict)

    def for_task(self, task: str) -> LLMParams:
        """Task overrides from [llm.tasks.<task>] on top of the [llm] defaults."""
        base = self.model_dump(exclude={"tasks"})
        return LLMParams(**{**base, **self.tasks.get(task, {})})


class EmbeddingConfig(BaseModel):
    provider: str = "openai"
    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    batch_size: int = 64


class VectorsConfig(BaseModel):
    metric: str = "COSINE"
    memory_collection: str = "memory_cards"
    jobs_collection: str = "jobs"
    requirements_collection: str = "job_requirements"


class VaultConfig(BaseModel):
    max_upload_mb: float = 10
    allowed_types: list[str] = Field(default_factory=lambda: ["pdf", "docx"])
    min_text_chars: int = 200


class ProfileConfig(BaseModel):
    fill_default_mode: str = "empty_only"
    skill_groups_max: int = 8


class MemoryConfig(BaseModel):
    max_card_chars: int = 1500


class RecordsConfig(BaseModel):
    vault: VaultConfig = Field(default_factory=VaultConfig)
    profile: ProfileConfig = Field(default_factory=ProfileConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)


class AppConfig(BaseModel):
    name: str = "SmartIntern"


class SnapshotConfig(BaseModel):
    debounce_seconds: float = 2.0


class Tuning(BaseModel):
    # Sections for later phases may appear in the file before code reads them.
    model_config = ConfigDict(extra="allow")

    app: AppConfig = Field(default_factory=AppConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    vectors: VectorsConfig = Field(default_factory=VectorsConfig)
    records: RecordsConfig = Field(default_factory=RecordsConfig)
    snapshot: SnapshotConfig = Field(default_factory=SnapshotConfig)
    # Job Search defaults ([scout.search.<section>]); validated by services/search_settings.py
    # against backend/job_schemas.py, because the UI can override them.
    scout: dict = Field(default_factory=dict)
    loaded_from: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


class ConfigWriteError(RuntimeError):
    """config.toml could not be written (read-only mount, missing file, bad value)."""


_tuning_lock = threading.RLock()
_tuning_cache: dict[str, Any] = {"stamp": None, "tuning": None, "raw": {}, "error": None}


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _load_tuning(s: Settings) -> tuple[Tuning, dict]:
    raw: dict = {}
    loaded_from = None
    if s.config_file.is_file():
        with s.config_file.open("rb") as f:
            raw = tomllib.load(f)
        loaded_from = str(s.config_file)
    tuning = Tuning(**raw, loaded_from=loaded_from)
    if s.llm_provider:
        tuning.llm.provider = s.llm_provider
    if s.llm_model:
        tuning.llm.model = s.llm_model
    return tuning, raw


def get_tuning() -> Tuning:
    """config.toml, re-read when the file changes. Cheap to call (one stat)."""
    s = get_settings()
    stamp = _stamp(s.config_file)
    c = _tuning_cache
    if c["tuning"] is not None and c["stamp"] == stamp:
        return c["tuning"]
    with _tuning_lock:
        if c["tuning"] is not None and c["stamp"] == stamp:
            return c["tuning"]
        try:
            tuning, c["raw"] = _load_tuning(s)
            c["error"] = None
        except Exception as e:  # noqa: BLE001 - a broken hand edit must not take the app down
            c["error"] = f"{type(e).__name__}: {e}"
            log.warning("config.toml unreadable, keeping the last good values: %s", c["error"])
            tuning = c["tuning"] or Tuning()
        c["stamp"], c["tuning"] = stamp, tuning
        return tuning


def _reset_tuning_cache() -> None:
    with _tuning_lock:
        _tuning_cache.update(stamp=None, tuning=None, raw={}, error=None)


get_tuning.cache_clear = _reset_tuning_cache  # type: ignore[attr-defined]  # old lru_cache API


def tuning_raw() -> dict:
    """config.toml exactly as written (no env overrides, no code defaults). A deep copy."""
    import copy

    get_tuning()
    return copy.deepcopy(_tuning_cache["raw"])


def tuning_stamp() -> str:
    """Changes whenever config.toml changes; lets the UI detect edits made elsewhere."""
    st = _stamp(get_settings().config_file)
    return f"{st[0]}-{st[1]}" if st else "missing"


def tuning_error() -> str | None:
    """Why the current config.toml couldn't be read (the last good values are in use)."""
    get_tuning()
    return _tuning_cache["error"]


def env_overrides() -> dict[str, str]:
    """config.toml keys currently overridden by the environment (env wins)."""
    s = get_settings()
    return {k: v for k, v in (("llm.provider", s.llm_provider), ("llm.model", s.llm_model)) if v}


def write_tuning(changes: dict[tuple[str, ...], Any]) -> None:
    """Set (or, with value None, remove) keys in config.toml, keeping comments and layout.

    Keys are paths like ("scout", "search", "matching", "role_threshold"). Missing tables are
    created. The file is rewritten in place, then re-read on the next `get_tuning()`.
    """
    import tomlkit  # optional subsystem: only the Admin page writes the file

    path = get_settings().config_file
    with _tuning_lock:
        try:
            # Bytes, not read_text(): keep the file's own line endings (CRLF on Windows checkouts),
            # so a save changes only the edited lines.
            doc = tomlkit.parse(path.read_bytes().decode("utf-8")) if path.is_file() else tomlkit.document()
        except Exception as e:  # noqa: BLE001
            raise ConfigWriteError(f"config.toml has a syntax error, fix it first: {e}") from e
        for keys, value in changes.items():
            table = doc
            for k in keys[:-1]:
                if k not in table:
                    table.add(k, tomlkit.table())
                table = table[k]
            if value is None:
                if keys[-1] in table:
                    del table[keys[-1]]
            elif keys[-1] in table:
                table[keys[-1]] = value
            else:
                table.add(tomlkit.nl())
                table.add(keys[-1], value)
        text = tomlkit.dumps(doc)
        try:
            # Same file, rewritten in place: a rename would break a single-file bind mount.
            with path.open("w", encoding="utf-8", newline="") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            raise ConfigWriteError(
                f"Couldn't write {path}: {e.strerror or e}. In Docker, settings/ must be mounted read-write."
            ) from e
        _tuning_cache["stamp"] = None  # force a re-read


def data_dir() -> Path:
    d = get_settings().data_dir
    d.mkdir(parents=True, exist_ok=True)
    return d
