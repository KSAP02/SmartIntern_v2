"""Records / Vault: the resume library."""
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Response, UploadFile, status
from sqlmodel import Session

from backend.db import Resume, get_session, utcnow
from backend.schemas import ResumeDetail, ResumeOut, ResumePatch, UploadResult
from backend.services import vault
from backend.storage import get_storage

router = APIRouter(prefix="/records/vault", tags=["records: vault"])


def _get(session: Session, resume_id: int) -> Resume:
    r = session.get(Resume, resume_id)
    if r is None:
        raise HTTPException(404, f"Resume {resume_id} not found.")
    return r


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=UploadResult)
async def upload(
    background: BackgroundTasks, files: list[UploadFile] = File(...), session: Session = Depends(get_session)
):
    result = UploadResult(items=[], duplicates=[], errors=[])
    for f in files:
        data = await f.read()
        r, duplicate, error = vault.add_upload(session, f.filename or "resume", data)
        if error:
            result.errors.append(error)
            continue
        assert r is not None and r.id is not None
        result.items.append(vault.resume_out(r))
        if duplicate:
            result.duplicates.append(r.id)
        else:
            background.add_task(vault.parse_resume, r.id)
    if not result.items:
        raise HTTPException(400, "; ".join(f"{e.filename}: {e.detail}" for e in result.errors) or "No files received.")
    return result


@router.get("", response_model=list[ResumeOut])
def list_resumes(session: Session = Depends(get_session)):
    return [vault.resume_out(r) for r in vault.list_resumes(session)]


@router.get("/{resume_id}", response_model=ResumeDetail)
def get_resume(resume_id: int, session: Session = Depends(get_session)):
    return vault.resume_detail(_get(session, resume_id))


@router.get("/{resume_id}/file")
def get_file(resume_id: int, session: Session = Depends(get_session)):
    r = _get(session, resume_id)
    data = get_storage().read(r.storage_key)
    safe = r.original_filename.replace('"', "")
    return Response(data, media_type=r.mime_type, headers={"Content-Disposition": f'inline; filename="{safe}"'})


@router.patch("/{resume_id}", response_model=ResumeOut)
def patch_resume(resume_id: int, body: ResumePatch, session: Session = Depends(get_session)):
    r = _get(session, resume_id)
    if body.label is not None:
        label = body.label.strip()
        if not label:
            raise HTTPException(422, "Label can't be empty.")
        r.label = label[:120]
    if body.is_default:
        vault.set_default(session, r)
    r.updated_at = utcnow()
    session.add(r)
    session.commit()
    session.refresh(r)
    return vault.resume_out(r)


@router.post("/{resume_id}/reparse", status_code=status.HTTP_202_ACCEPTED, response_model=ResumeOut)
def reparse(resume_id: int, background: BackgroundTasks, session: Session = Depends(get_session)):
    r = _get(session, resume_id)
    if r.parse_status == "parsing":
        raise HTTPException(409, "This resume is already being parsed.")
    r.parse_status, r.parse_error, r.updated_at = "pending", None, utcnow()
    session.add(r)
    session.commit()
    session.refresh(r)
    background.add_task(vault.parse_resume, resume_id)
    return vault.resume_out(r)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(resume_id: int, session: Session = Depends(get_session)):
    vault.delete_resume(session, _get(session, resume_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
