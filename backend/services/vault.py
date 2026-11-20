"""Vault (resume library): upload validation, storage, background parsing."""
from __future__ import annotations

import hashlib
import logging
from pathlib import PurePath

from sqlmodel import Session, select

from backend.config import get_tuning
from backend.db import Resume, new_session, utcnow
from backend.schemas import Profile, ResumeDetail, ResumeOut, UploadError
from backend.services.profile_extract import extract_profile
from backend.services.resume_text import MIME, ResumeTextError, detect_type, extract_text
from backend.storage import get_storage

log = logging.getLogger(__name__)


def resume_out(r: Resume) -> ResumeOut:
    return ResumeOut(
        id=r.id,  # type: ignore[arg-type]
        label=r.label,
        original_filename=r.original_filename,
        mime_type=r.mime_type,
        size_bytes=r.size_bytes,
        parse_status=r.parse_status,  # type: ignore[arg-type]
        parse_error=r.parse_error,
        is_default=r.is_default,
        has_parsed_data=r.parsed_data is not None,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def resume_detail(r: Resume) -> ResumeDetail:
    return ResumeDetail(
        **resume_out(r).model_dump(),
        extracted_text=r.extracted_text,
        parsed_data=Profile.model_validate(r.parsed_data) if r.parsed_data else None,
    )


def list_resumes(session: Session) -> list[Resume]:
    return list(session.exec(select(Resume).order_by(Resume.created_at.desc())).all())  # type: ignore[attr-defined]


def add_upload(session: Session, filename: str, data: bytes) -> tuple[Resume | None, bool, UploadError | None]:
    """Validate and store one file. Returns (resume, was_duplicate, error)."""
    cfg = get_tuning().records.vault
    name = PurePath(filename or "resume").name
    if not data:
        return None, False, UploadError(filename=name, detail="The file is empty.")
    if len(data) > cfg.max_upload_mb * 1024 * 1024:
        return None, False, UploadError(filename=name, detail=f"File is larger than {cfg.max_upload_mb:g} MB.")
    kind = detect_type(name, data)
    if kind is None or kind not in cfg.allowed_types:
        allowed = ", ".join(t.upper() for t in cfg.allowed_types)
        return None, False, UploadError(filename=name, detail=f"Not a valid {allowed} file.")

    sha = hashlib.sha256(data).hexdigest()
    existing = session.exec(select(Resume).where(Resume.sha256 == sha)).first()
    if existing:
        return existing, True, None

    key = get_storage().save(f"resumes/{sha}.{kind}", data)
    has_default = session.exec(select(Resume).where(Resume.is_default == True)).first() is not None  # noqa: E712
    r = Resume(
        label=PurePath(name).stem[:120] or "Resume",
        original_filename=name,
        mime_type=MIME[kind],
        size_bytes=len(data),
        sha256=sha,
        storage_key=key,
        is_default=not has_default,
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    return r, False, None


def parse_resume(resume_id: int) -> None:
    """Background task: extract text, then structured data. Never touches the profile."""
    with new_session() as session:
        r = session.get(Resume, resume_id)
        if r is None:
            return
        r.parse_status, r.parse_error, r.updated_at = "parsing", None, utcnow()
        session.add(r)
        session.commit()
        try:
            data = get_storage().read(r.storage_key)
            kind = "pdf" if r.mime_type == MIME["pdf"] else "docx"
            text = extract_text(data, kind)
            r.extracted_text = text
            if len(text) < get_tuning().records.vault.min_text_chars:
                raise ResumeTextError(
                    "Very little text could be read. This looks like a scanned/image PDF; "
                    "upload a text-based PDF or a DOCX."
                )
            r.parsed_data = extract_profile(text).model_dump()
            r.parse_status = "parsed"
        except Exception as e:  # noqa: BLE001 - message is shown to the user
            log.warning("resume %s failed to parse: %s", resume_id, e.__class__.__name__)
            r.parse_status, r.parse_error = "failed", str(e)[:500]
        r.updated_at = utcnow()
        session.add(r)
        session.commit()


def requeue_unfinished() -> list[int]:
    """Resumes left pending/parsing by a restart are put back in the queue."""
    with new_session() as session:
        stuck = session.exec(select(Resume).where(Resume.parse_status.in_(["pending", "parsing"]))).all()  # type: ignore[attr-defined]
        ids = []
        for r in stuck:
            r.parse_status = "pending"
            session.add(r)
            ids.append(r.id)
        session.commit()
        return ids


def set_default(session: Session, r: Resume) -> None:
    for other in session.exec(select(Resume).where(Resume.is_default == True)).all():  # noqa: E712
        other.is_default = False
        session.add(other)
    r.is_default = True


def delete_resume(session: Session, r: Resume) -> None:
    get_storage().delete(r.storage_key)
    was_default = r.is_default
    session.delete(r)
    session.commit()
    if was_default:
        newest = session.exec(select(Resume).order_by(Resume.created_at.desc())).first()  # type: ignore[attr-defined]
        if newest:
            newest.is_default = True
            session.add(newest)
            session.commit()
