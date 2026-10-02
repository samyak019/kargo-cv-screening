import itertools
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rubric  # noqa: E402
import screen  # noqa: E402
from calibration_profiles import EXPECTED, FACTS  # noqa: E402
from rubric import ROLES, Facts  # noqa: E402


def facts_for(name, parse_confidence="high"):
    g1, pm_years, ops_years, own_years, mumbai = FACTS[name]
    return Facts(g1, pm_years, ops_years, own_years, mumbai, parse_confidence)


def calibration_cases():
    for role_key, profiles in EXPECTED.items():
        for name, (scores, total, route) in profiles.items():
            yield pytest.param(role_key, name, scores, total, route, id=f"{role_key}-{name}")


# ------------------------------------------------------------------ weights

@pytest.mark.parametrize("role_key", list(ROLES))
def test_weights_sum_to_100(role_key):
    assert sum(c.weight for c in ROLES[role_key].criteria) == 100


@pytest.mark.parametrize("role_key", list(ROLES))
def test_six_unique_criteria(role_key):
    ids = ROLES[role_key].ids
    assert len(ids) == 6 and len(set(ids)) == 6


# -------------------------------------------------------------- calibration

@pytest.mark.parametrize("role_key,name,scores,total,route", calibration_cases())
def test_section6_reproduces(role_key, name, scores, total, route):
    role = ROLES[role_key]
    d = rubric.decide(role, dict(zip(role.ids, scores)), facts_for(name))
    assert d.total == pytest.approx(total)
    assert d.route == route


@pytest.mark.parametrize("role_key,name,scores,total,route", calibration_cases())
def test_section6_routes_hold_within_plus_minus_one(role_key, name, scores, total, route):
    """LLM scores will drift by a point. No combination of +/-1 per criterion
    may move a Section 6 profile all the way from ADVANCE to REJECT or back."""
    role = ROLES[role_key]
    facts = facts_for(name)
    for deltas in itertools.product((-1, 0, 1), repeat=6):
        s = {cid: min(4, max(0, v + dv)) for cid, v, dv in zip(role.ids, scores, deltas)}
        got = rubric.decide(role, s, facts).route
        assert {got, route} != {rubric.ADVANCE, rubric.REJECT}, (deltas, got)


def test_no_inferred_high_hire_rejected():
    high = ["Rohan Desai", "Sunita Krishnamurthy", "Lavanya Iyer", "Meghna Tiwari", "Aditya Shetty"]
    for role_key, profiles in EXPECTED.items():
        for name in high:
            assert profiles[name][2] != rubric.REJECT, (role_key, name)


def test_lavanya_spm_gets_f1():
    role = ROLES["SPM"]
    scores, _, _ = EXPECTED["SPM"]["Lavanya Iyer"]
    d = rubric.decide(role, dict(zip(role.ids, scores)), facts_for("Lavanya Iyer"))
    assert "F1 probe seniority" in d.flags


def test_vikram_rescued_by_r2_for_pm_only():
    for role_key, expected_route in (("PM", rubric.REVIEW), ("SPM", rubric.REJECT)):
        role = ROLES[role_key]
        scores, _, _ = EXPECTED[role_key]["Vikram Nair"]
        d = rubric.decide(role, dict(zip(role.ids, scores)), facts_for("Vikram Nair"))
        assert d.route == expected_route
        assert ("R2" in d.rules_fired) == (role_key == "PM")


# ------------------------------------------------------------- rule edges

def plain_facts(**kw):
    base = dict(g1_pass=True, pm_title_years=0, ops_tenure_years=0,
                ownership_role_years=10, mumbai_in_office_stated=True, parse_confidence="high")
    base.update(kw)
    return Facts(**base)


def test_boundaries():
    pm = ROLES["PM"]
    # 75.00 exactly with G1 -> ADVANCE
    s75 = dict(zip(pm.ids, [3, 3, 3, 3, 3, 3]))
    assert rubric.decide(pm, s75, plain_facts()).route == rubric.ADVANCE
    assert rubric.decide(pm, s75, plain_facts(g1_pass=False)).route == rubric.REVIEW
    # 55.00 exactly -> REVIEW; 52.50 -> REJECT
    s55 = dict(zip(pm.ids, [2, 3, 2, 2, 2, 2]))
    assert rubric.weighted_score(pm, s55) == 55.0
    assert rubric.decide(pm, s55, plain_facts()).route == rubric.REVIEW
    s_low = dict(zip(pm.ids, [2, 2, 2, 2, 2, 3]))
    assert rubric.weighted_score(pm, s_low) == 52.5
    assert rubric.decide(pm, s_low, plain_facts()).route == rubric.REJECT


@pytest.mark.parametrize("rule,kw,scores", [
    ("R1", {}, [0, 0, 4, 4, 0, 0]),
    ("R2", {"pm_title_years": 2}, [0] * 6),
    ("R3", {"ops_tenure_years": 2}, [0] * 6),
    ("R4", {"parse_confidence": "low"}, [0] * 6),
])
def test_each_rescue_rule_saves_a_reject(rule, kw, scores):
    pm = ROLES["PM"]
    d = rubric.decide(pm, dict(zip(pm.ids, scores)), plain_facts(**kw))
    assert d.route == rubric.REVIEW and rule in d.rules_fired


def test_f2_when_mumbai_not_stated():
    pm = ROLES["PM"]
    d = rubric.decide(pm, dict(zip(pm.ids, [0] * 6)), plain_facts(mumbai_in_office_stated=False))
    assert "F2 confirm in-office" in d.flags


def test_bad_scores_raise():
    pm = ROLES["PM"]
    with pytest.raises(ValueError):
        rubric.weighted_score(pm, dict(zip(pm.ids, [5, 0, 0, 0, 0, 0])))
    with pytest.raises(ValueError):
        rubric.weighted_score(pm, {"C1": 4})


# ------------------------------------------------------- quote verification

CV = """Rohan Desai — Mumbai
• Built a BL-verification prototype over a weekend; 30 users in 1 month, now a core feature.
Cut P1 incidents by 40% after owning the vendor migration.
B.E. Mechanical, University of Mumbai
"""


def fake_assessment(criteria, **kw):
    base = dict(candidate_name="Rohan Desai", g1_pass=True,
                g1_quote="owning the vendor migration", pm_title_years=0, ops_tenure_years=3,
                ownership_role_years=5, mumbai_in_office_stated=True, mumbai_quote="Rohan Desai — Mumbai",
                parse_confidence="high", brief="")
    base.update(kw)
    return screen.Assessment(criteria=[screen.CriterionResult(**c) for c in criteria], **base)


def test_score_reset_when_quote_not_in_cv():
    role = ROLES["PM"]
    crit = [dict(id=cid, score=3, evidence=["Led a global transformation programme"], reason="x")
            for cid in role.ids]
    scores, ev, _ = screen.verify(role, fake_assessment(crit), CV)
    assert all(v == 0 for v in scores.values())
    assert ev["C1"]["dropped"][0]["why"] == "not found in CV"


def test_quote_match_tolerates_whitespace_and_punctuation():
    role = ROLES["PM"]
    crit = [dict(id="C3", score=4, reason="x",
                 evidence=["Built a BL-verification prototype over a weekend;  30 users in 1 month"])]
    crit += [dict(id=cid, score=0, evidence=[], reason="x") for cid in role.ids if cid != "C3"]
    scores, _, _ = screen.verify(role, fake_assessment(crit), CV)
    assert scores["C3"] == 4


def test_credential_quotes_never_score():
    role = ROLES["PM"]
    crit = [dict(id=cid, score=2, evidence=["B.E. Mechanical, University of Mumbai"], reason="x")
            for cid in role.ids]
    scores, ev, _ = screen.verify(role, fake_assessment(crit), CV)
    assert all(v == 0 for v in scores.values())
    assert "credential" in ev["C1"]["dropped"][0]["why"]


def test_g1_and_mumbai_need_verified_quotes():
    role = ROLES["PM"]
    crit = [dict(id=cid, score=0, evidence=[], reason="x") for cid in role.ids]
    _, _, facts = screen.verify(role, fake_assessment(crit), CV)
    assert facts.g1_pass and facts.mumbai_in_office_stated
    _, _, facts = screen.verify(role, fake_assessment(
        crit, g1_quote="owned the platform", mumbai_quote="relocating to Mumbai"), CV)
    assert not facts.g1_pass and not facts.mumbai_in_office_stated


def test_short_text_is_low_confidence():
    role = ROLES["PM"]
    crit = [dict(id=cid, score=0, evidence=[], reason="x") for cid in role.ids]
    _, _, facts = screen.verify(role, fake_assessment(crit), "Rohan Desai")
    assert facts.parse_confidence == "low"


def test_missing_criterion_scores_zero():
    role = ROLES["PM"]
    _, ev, _ = screen.verify(role, fake_assessment([]), CV)
    assert ev["C1"]["score"] == 0 and "missing" in ev["C1"]["reason"]


# ---------------------------------------------------------------- calibrate

def test_spearman():
    assert screen.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert screen.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert screen.spearman([1, 2], [1, 2]) is None
    assert screen.spearman([1, 1, 1], [1, 2, 3]) is None


def test_calibrate_reports_rejected_high_raters(tmp_path, capsys):
    (tmp_path / "results.csv").write_text(
        "candidate,file,role,total,route\n"
        "Rahul Bose,r.docx,PM,41.25,REJECT\n"
        "Rohan Desai,ro.docx,PM,87.50,ADVANCE\n"
        "Aditya Shetty,a.docx,PM,65.00,HUMAN REVIEW\n")
    (tmp_path / "ratings.csv").write_text(
        "name,role,actual_rating\nRahul Bose,PM,4\nRohan Desai,PM,5\nAditya Shetty,PM,3\n")
    assert screen.calibrate(tmp_path / "results.csv", tmp_path / "ratings.csv") == 0
    out = capsys.readouterr().out
    assert "Rahul Bose (rating 4" in out


# ------------------------------------------------------- live (costs money)

LIVE = os.environ.get("KARGO_LIVE") == "1" and os.environ.get("ANTHROPIC_API_KEY")


@pytest.mark.skipif(not LIVE, reason="set KARGO_LIVE=1 and ANTHROPIC_API_KEY to run against the real CVs")
@pytest.mark.parametrize("role_key,name,scores,total,route", calibration_cases())
def test_live_cv_matches_section6(role_key, name, scores, total, route):
    """Screens the real CV and checks each criterion is within +/-1 of
    Section 6 and the route matches. CV file is found by first name."""
    import anthropic

    first = name.split()[0].lower()
    files = [p for p in (ROOT / "cvs").iterdir()
             if first in p.name.lower() and p.suffix.lower() in (".docx", ".pdf")]
    if not files:
        pytest.skip(f"no CV in cvs/ matching '{first}'")
    role = ROLES[role_key]
    text = screen.extract_text(files[0])
    a = screen.assess(anthropic.Anthropic(), os.environ.get("KARGO_MODEL", screen.DEFAULT_MODEL),
                      role, text)
    got, _, facts = screen.verify(role, a, text)
    off = {cid: (got[cid], want) for cid, want in zip(role.ids, scores) if abs(got[cid] - want) > 1}
    assert not off, f"criteria more than 1 off (got, expected): {off}"
    assert rubric.decide(role, got, facts).route == route


# ------------------------------------------------------------------ report

def test_report_renders_and_escapes(tmp_path):
    import json
    import report

    role = ROLES["PM"]
    rows = [dict(candidate="<script>alert(1)</script>", file="x.docx", role="PM",
                 **dict(zip(role.ids, [4, 3, 4, 4, 3, 2])), total="87.50", g1="Y",
                 route=rubric.ADVANCE, route_reason="score >= 75 and G1 pass",
                 rules_fired="R3", flags="F2 confirm in-office", error=""),
            dict(candidate="broken", file="y.pdf", role="PM", route=rubric.REVIEW,
                 route_reason="R4 unreadable CV", rules_fired="R4", error="no text extracted")]
    ev = {"x.docx": {"PM": {"C1": {"score": 4, "model_score": 4, "evidence": ["a </script> quote"],
                                   "dropped": [], "reason": "r"}, "_brief": "b", "_facts": {"g1_pass": True}}}}
    out = report.render(rows, ev, tmp_path / "report.html", "m")
    page = out.read_text()
    assert "<script>alert(1)</script>" not in page and "a </script> quote" not in page
    blob = page.split('type="application/json">', 1)[1].split("</script>", 1)[0]
    data = json.loads(blob)
    first = data["candidates"][0]
    assert first["roles"]["PM"]["rank"] == 1 and first["roles"]["PM"]["criteria"][0]["evidence"]
    assert data["candidates"][1]["roles"]["PM"]["total"] is None


# ------------------------------------------------- redaction + incremental

def test_redact_strips_contact_details():
    out = screen.redact("Asha Rao | asha.rao@gmail.com | +91 98202 11345 | cut lag from 4h to 8m in 2023")
    assert "@" not in out and "98202" not in out
    assert "[email]" in out and "[phone]" in out and "4h to 8m in 2023" in out


def test_only_new_or_changed_cvs_are_scored(tmp_path, monkeypatch):
    import docx

    cvs = tmp_path / "cvs"
    cvs.mkdir()

    def make(name, extra=""):
        d = docx.Document()
        for line in [name, "Ops executive at a customs house agent for 3 years. " + extra] + ["work"] * 60:
            d.add_paragraph(line)
        d.save(cvs / (name.split()[0].lower() + ".docx"))

    calls = []

    def fake(client, model, role, text):
        calls.append(role.key)
        crit = [screen.CriterionResult(id=c, score=3, evidence=["Ops executive at a customs house agent"],
                                       reason="r") for c in role.ids]
        return screen.Assessment(candidate_name=text.splitlines()[0], criteria=crit, g1_pass=False,
                                 g1_quote="", pm_title_years=0, ops_tenure_years=3,
                                 ownership_role_years=2, mumbai_in_office_stated=False,
                                 mumbai_quote="", parse_confidence="high", brief="b")

    monkeypatch.setattr(screen, "assess", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    roles = list(ROLES.values())

    make("Asha Rao"); make("Bilal Khan")
    screen.screen(cvs, tmp_path, roles, "m")
    assert len(calls) == 4
    calls.clear(); make("Chitra Nair")
    screen.screen(cvs, tmp_path, roles, "m")
    assert len(calls) == 2
    calls.clear(); make("Bilal Khan", "edited")
    screen.screen(cvs, tmp_path, roles, "m")
    assert len(calls) == 2
    calls.clear()
    screen.screen(cvs, tmp_path, roles, "m", rescore=True)
    assert len(calls) == 6
    assert (tmp_path / "report.html").exists()
