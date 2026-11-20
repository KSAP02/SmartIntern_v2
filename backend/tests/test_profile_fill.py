from backend.schemas import Profile
from backend.services.profile_fill import apply_changes, completeness, compute_changes, mark_user_edits
from backend.tests.conftest import fake_profile


def _fill(current, incoming, origins, mode, exclude=(), resume_id=1):
    changes = compute_changes(current, incoming, origins, mode)
    return apply_changes(current, changes, set(exclude), origins, resume_id)


def test_fill_into_empty_profile_copies_everything_and_tags_origin():
    profile, origins, applied = _fill(Profile(), fake_profile(), {}, "empty_only")
    assert profile.personal.full_name == "Alex Example"
    assert len(profile.work_history) == 1 and profile.work_history[0].id
    assert origins["personal.full_name"] == "resume:1"
    assert origins[f"work_history[{profile.work_history[0].id}]"] == "resume:1"
    assert applied > 5
    assert profile.preferences == Profile().preferences  # never filled from a resume


def test_empty_only_keeps_user_edits_and_fills_blanks():
    current, origins, _ = _fill(Profile(), fake_profile(), {}, "empty_only")
    edited = current.model_copy(deep=True)
    edited.personal.phone = "+1 555 9999"
    edited.personal.address.city = None  # user cleared it on purpose
    origins = mark_user_edits(current, edited, origins)
    assert origins["personal.phone"] == "user"

    resume_b = fake_profile(personal={"full_name": "Alex Example", "phone": "+1 555 0200",
                                      "email": "alex.example@example.com",
                                      "address": {"city": "Shelbyville", "postal_code": "12345"}})
    profile, origins, _ = _fill(edited, resume_b, origins, "empty_only", resume_id=2)
    assert profile.personal.phone == "+1 555 9999"  # hand edit kept
    assert profile.personal.address.city is None  # user-cleared field not refilled
    assert profile.personal.address.postal_code == "12345"  # blank filled
    assert origins["personal.address.postal_code"] == "resume:2"


def test_list_entries_merge_instead_of_duplicating():
    current, origins, _ = _fill(Profile(), fake_profile(), {}, "empty_only")
    again = fake_profile(work_history=[
        {"company": "ACME widgets", "title": "Software engineering intern", "location": "Remote"},
        {"company": "Globex", "title": "Data Intern"},
    ])
    changes = compute_changes(current, again, origins, "empty_only")
    actions = sorted(c.action for c in changes if c.section == "work_history")
    assert actions == ["add", "update"]
    profile, _, _ = apply_changes(current, changes, set(), origins, 2)
    assert len(profile.work_history) == 2
    assert profile.work_history[0].location == "Remote"


def test_replace_flags_user_edits_and_exclude_skips_them():
    current, origins, _ = _fill(Profile(), fake_profile(), {}, "empty_only")
    edited = current.model_copy(deep=True)
    edited.personal.email = "mine@example.com"
    origins = mark_user_edits(current, edited, origins)
    changes = compute_changes(edited, fake_profile(), origins, "replace")
    email = next(c for c in changes if c.path == "personal.email")
    assert email.user_edited
    profile, _, _ = apply_changes(edited, changes, {"personal.email"}, origins, 1)
    assert profile.personal.email == "mine@example.com"


def test_preview_is_empty_when_nothing_new():
    current, origins, _ = _fill(Profile(), fake_profile(), {}, "empty_only")
    assert compute_changes(current, fake_profile(), origins, "empty_only") == []


def test_completeness_counts_preferences():
    p = fake_profile()
    before = completeness(p)
    p.preferences.roles_of_interest = ["Backend intern"]
    assert completeness(p) > before
