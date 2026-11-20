from backend.schemas import Profile, SkillGroup, Skills
from backend.services import skill_groups
from backend.services.memory import build_specs
from backend.services.profile_fill import apply_changes, compute_changes
from backend.tests.conftest import fake_profile


def test_old_flat_lists_become_two_groups():
    s = Skills.model_validate({"skills": ["Python"], "tools": ["Docker", "Git"], "languages": ["English"]})
    assert [(g.name, g.items) for g in s.groups] == [("Skills", ["Python"]), ("Tools & technologies", ["Docker", "Git"])]
    assert s.languages == ["English"]


def test_regroup_never_invents_or_loses_skills(monkeypatch):
    out = skill_groups._Grouping(groups=[
        skill_groups._Group(name="Backend & APIs", items=["python", "FastAPI", "Kubernetes"]),  # Kubernetes invented
        skill_groups._Group(name="Empty", items=[]),
    ])
    monkeypatch.setattr(skill_groups, "chat_structured", lambda **_: out)
    current = [SkillGroup(name="Skills", items=["Python", "FastAPI", "Docker"]), SkillGroup(name="Tools", items=["FastAPI"])]
    groups = skill_groups.regroup(current)
    assert [(g.name, g.items) for g in groups] == [("Backend & APIs", ["Python", "FastAPI"]), ("Other", ["Docker"])]


def test_fill_empty_only_adds_new_skills_into_matching_group():
    current = Profile(skills=Skills(groups=[SkillGroup(name="Backend", items=["Python"])]))
    incoming = fake_profile(skills={"groups": [{"name": "backend", "items": ["Python", "FastAPI"]},
                                               {"name": "Cloud", "items": ["Docker"]}]})
    changes = [c for c in compute_changes(current, incoming, {}, "empty_only") if c.section == "skills"]
    assert len(changes) == 1 and changes[0].path == "skills.groups"
    profile, origins, _ = apply_changes(current, changes, set(), {}, 3)
    assert [(g.name, g.items) for g in profile.skills.groups] == [("Backend", ["Python", "FastAPI"]), ("Cloud", ["Docker"])]
    assert profile.skills.groups[0].id == current.skills.groups[0].id  # existing group (and its card) kept
    assert origins["skills.groups"] == "resume:3"


def test_one_memory_card_per_group():
    p = Profile(skills=Skills(groups=[SkillGroup(name="AI / ML", items=["PyTorch"]), SkillGroup(name="Data", items=[])],
                              languages=["English"]))
    cards = [s for s in build_specs(p) if s.kind == "skills"]
    assert [c.title for c in cards] == ["AI / ML", "Languages"]
    assert cards[0].text == "AI / ML: PyTorch"
