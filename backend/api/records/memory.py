"""Records / Memory: context cards (stored text) and role contexts (Phase 2.6).

Cards are the material; each role in "Roles you want" gets a job-description-style role
context written from them (Memory -> Role contexts), which is what fetched jobs are compared
with. Cards are no longer embedded.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlmodel import Session

from backend.config import get_tuning
from backend.db import MemoryCard, RoleContext, get_session, utcnow
from backend.job_schemas import RoleContextOut, RoleContextPatch, RoleMatch, RoleTest
from backend.schemas import CardCreate, CardOut, CardPatch, MemoryOut
from backend.services import compass, job_search, memory, role_contexts, search_settings

router = APIRouter(prefix="/records/memory", tags=["records: memory"])


def _get(session: Session, card_id: int) -> MemoryCard:
    c = session.get(MemoryCard, card_id)
    if c is None:
        raise HTTPException(404, f"Card {card_id} not found.")
    return c


def _clip(text: str) -> str:
    return text.strip()[: get_tuning().records.memory.max_card_chars]


@router.get("", response_model=MemoryOut)
def list_cards(session: Session = Depends(get_session)):
    return memory.memory_out(session)


@router.post("", response_model=CardOut, status_code=status.HTTP_201_CREATED)
def add_card(body: CardCreate, background: BackgroundTasks, session: Session = Depends(get_session)):
    position = max((c.position for c in memory.list_cards(session)), default=-1) + 1
    c = MemoryCard(kind="custom", title=body.title.strip()[:200], text=_clip(body.text), origin="user", position=position,
                   embedding_status="none")
    session.add(c)
    session.commit()
    session.refresh(c)
    background.add_task(memory.after_change)
    return memory.card_out(c)


@router.patch("/{card_id}", response_model=CardOut)
def patch_card(card_id: int, body: CardPatch, background: BackgroundTasks, session: Session = Depends(get_session)):
    c = _get(session, card_id)
    changed = False
    if body.title is not None and body.title.strip() and body.title.strip() != c.title:
        c.title, changed = body.title.strip()[:200], True
    if body.text is not None and body.text.strip() and _clip(body.text) != c.text:
        c.text, changed = _clip(body.text), True
    if changed and c.origin == "generated":
        c.user_edited = True
    if body.enabled is not None and body.enabled != c.enabled:
        c.enabled, changed = body.enabled, True
    if body.pinned is not None:
        c.pinned = body.pinned
    c.updated_at = utcnow()
    session.add(c)
    session.commit()
    session.refresh(c)
    if changed:
        background.add_task(memory.after_change)  # evidence uses card text; role contexts show "memory changed"
    return memory.card_out(c)


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card(card_id: int, background: BackgroundTasks, session: Session = Depends(get_session)):
    session.delete(_get(session, card_id))
    session.commit()
    background.add_task(memory.after_change)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/rebuild", response_model=MemoryOut)
def rebuild(background: BackgroundTasks, session: Session = Depends(get_session)):
    memory.rebuild(session)
    background.add_task(memory.after_change)
    return memory.memory_out(session)


# ── Role contexts ──────────────────────────────────────────────────────────────


def _role(session: Session, context_id: int) -> RoleContext:
    rc = role_contexts.get(session, context_id)
    if rc is None:
        raise HTTPException(404, f"Role context {context_id} not found.")
    return rc


def _rescore() -> None:
    """A role context changed: jobs are re-scored against it (no new job embeddings)."""
    compass.remap_all()


@router.get("/roles", response_model=list[RoleContextOut])
def list_roles(session: Session = Depends(get_session)):
    """Your roles (in your order) with their contexts; roles still being written show as missing / pending."""
    return role_contexts.list_out(session)


@router.post("/roles/ensure", response_model=list[RoleContextOut])
def ensure_roles(session: Session = Depends(get_session)):
    """Write contexts for roles that don't have one yet (or whose last try failed), in the background."""
    role_contexts.start_ensure()
    return role_contexts.list_out(session)


@router.patch("/roles/{context_id}", response_model=RoleContextOut)
def edit_role(context_id: int, body: RoleContextPatch, background: BackgroundTasks, session: Session = Depends(get_session)):
    """Save your edits (re-embeds the context, then jobs are re-scored)."""
    rc = role_contexts.update(session, _role(session, context_id), body)
    background.add_task(_rescore)
    return role_contexts.out(session, rc)


@router.post("/roles/{context_id}/regenerate", response_model=RoleContextOut)
def regenerate_role(context_id: int, background: BackgroundTasks, session: Session = Depends(get_session)):
    """Rewrite it with the AI model from your current cards (replaces your edits)."""
    role = _role(session, context_id).role
    if job_search.running_scan_id():
        raise HTTPException(409, "A scan is running; try again when it has finished.")
    rc = role_contexts.generate(role, force=True)
    if rc is None or rc.status == "failed":
        raise HTTPException(502, f"Couldn't write the role context: {rc.error if rc else 'unknown error'}")
    background.add_task(_rescore)
    session.expire_all()
    return role_contexts.out(session, _role(session, context_id))


@router.post("/roles/test", response_model=list[RoleMatch])
def test_roles(body: RoleTest, session: Session = Depends(get_session)):
    """Paste a job description: how close it is to each of your role contexts."""
    if not search_settings.get(session, "criteria").roles:
        raise HTTPException(400, "Add Roles you want first (Job Search -> Search Settings).")
    return role_contexts.test(session, body.text)
