"""Kargo PM / SPM rubric: criteria, weights, scoring and routing.

Everything here is deterministic code. The LLM only supplies per-criterion
scores (0-4) with quoted evidence and a few extracted facts; the weighted
score, gate, rescue rules, flags and route are all computed here.
Spec: kargo_pm_spm_rubric.txt, Sections 3-5.
"""
from dataclasses import dataclass, field
from typing import Dict, List

ADVANCE = "ADVANCE"
REVIEW = "HUMAN REVIEW"
REJECT = "REJECT"

ADVANCE_LINE = 75.0
REJECT_LINE = 55.0

SCORE_ANCHORS = """\
Score each criterion 0-4 on EVIDENCE only (a named artefact, a metric, an
adoption count, a quote from a reviewer). Adjectives score 0.
  4 = repeated, quantified, owned end-to-end
  3 = one clear quantified instance, owned
  2 = present but supporting role, or unquantified
  1 = adjacent / weak signal
  0 = absent"""

NEVER_SCORE = [
    "years of PM title",
    "school tier",
    "MBA",
    "certifications",
    "company brand",
    "conference talks",
    "tool lists",
]


@dataclass(frozen=True)
class Criterion:
    id: str
    name: str
    weight: float
    anchor: str


@dataclass(frozen=True)
class Role:
    key: str
    title: str
    criteria: List[Criterion]
    p1_id: str  # pattern P1 criterion (unprompted fix adopted), used by R1
    p2_id: str  # pattern P2 criterion (absorbs crises), used by R1
    pm_title_floor_years: float  # R2

    @property
    def ids(self) -> List[str]:
        return [c.id for c in self.criteria]


PM = Role(
    key="PM",
    title="Product Manager",
    criteria=[
        Criterion("C1", "Lived ground-level ops exposure", 25,
                  "Held a paid ops role in freight/3PL/supply chain. "
                  "4 = 2+ yrs doing the work; 1 = sold to / built for ops users only."),
        Criterion("C2", "Shipped AND killed, with outcome data", 20,
                  "4 = shipped + killed + adoption/usage metric; "
                  "2 = shipped, no kill, no adoption data."),
        Criterion("C3", "Unprompted fix adopted as team standard [P1]", 20,
                  "4 = built unasked AND adopted by others, counted. Work that was "
                  "part of the person's assigned remit scores lower."),
        Criterion("C4", "Absorbs crises without escalation [P2]", 15,
                  "4 = repeated, customer protected, owned to closure. "
                  "Incident work inside a rotation without end-to-end ownership scores lower."),
        Criterion("C5", "Operates without structure / early stage", 10,
                  "4 = sole owner, no handbook; 0 = large structured org."),
        Criterion("C6", "Written decision clarity", 10,
                  "Post-mortems, specs, API docs, kill rationale."),
    ],
    p1_id="C3",
    p2_id="C4",
    pm_title_floor_years=2.0,
)

SPM = Role(
    key="SPM",
    title="Senior Product Manager",
    criteria=[
        Criterion("S1", "Integration / data-layer depth", 25,
                  "APIs, carrier/3PL/vendor integrations, migrations, data quality. "
                  "4 = designed + owned, with metric."),
        Criterion("S2", "Consequential calls with no layer above", 20,
                  "4 = sole decision-owner, lived with the outcome."),
        Criterion("S3", "Lived ground-level ops exposure", 15,
                  "Held a paid ops role in freight/3PL/supply chain. "
                  "4 = 2+ yrs doing the work; 1 = sold to / built for ops users only."),
        Criterion("S4", "Unprompted fix adopted as team standard [P1]", 15,
                  "4 = built unasked AND adopted by others, counted. Work that was "
                  "part of the person's assigned remit scores lower."),
        Criterion("S5", "Multiplier - grows people & practices", 15,
                  "4 = mentee promoted / practice adopted org-wide "
                  "(maps to 'shape the PM function')."),
        Criterion("S6", "Absorbs crises / reliability under pressure [P2]", 10,
                  "4 = repeated, customer protected, owned to closure."),
    ],
    p1_id="S4",
    p2_id="S6",
    pm_title_floor_years=5.0,
)

ROLES: Dict[str, Role] = {PM.key: PM, SPM.key: SPM}

G1_DEFINITION = (
    "G1 - product/system ownership: has owned a product, module, platform or "
    "integration decision end-to-end (PM, eng lead owning a module, platform owner)."
)

F1_MIN_OWNERSHIP_YEARS = 4.0
R3_MIN_OPS_YEARS = 2.0


@dataclass
class Facts:
    """Non-scored facts extracted from the CV, used only by gates/rules/flags."""
    g1_pass: bool
    pm_title_years: float
    ops_tenure_years: float
    ownership_role_years: float
    mumbai_in_office_stated: bool
    parse_confidence: str  # "high" | "low"


@dataclass
class Decision:
    role: str
    scores: Dict[str, int]
    total: float
    g1_pass: bool
    route: str
    reason: str
    rules_fired: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)


def weighted_score(role: Role, scores: Dict[str, int]) -> float:
    missing = set(role.ids) - set(scores)
    if missing:
        raise ValueError(f"{role.key}: missing scores for {sorted(missing)}")
    for cid in role.ids:
        if not 0 <= scores[cid] <= 4:
            raise ValueError(f"{role.key}.{cid}: score {scores[cid]} outside 0-4")
    return round(sum(c.weight * scores[c.id] / 4 for c in role.criteria), 2)


def rescue_rules(role: Role, scores: Dict[str, int], facts: Facts) -> List[str]:
    fired = []
    if scores[role.p1_id] == 4 and scores[role.p2_id] == 4:
        fired.append("R1")
    if facts.pm_title_years >= role.pm_title_floor_years:
        fired.append("R2")
    if facts.ops_tenure_years >= R3_MIN_OPS_YEARS:
        fired.append("R3")
    if facts.parse_confidence == "low":
        fired.append("R4")
    return fired


def flags(role: Role, facts: Facts) -> List[str]:
    out = []
    if role.key == "SPM" and facts.ownership_role_years < F1_MIN_OWNERSHIP_YEARS:
        out.append("F1 probe seniority")
    if not facts.mumbai_in_office_stated:
        out.append("F2 confirm in-office")
    return out


def decide(role: Role, scores: Dict[str, int], facts: Facts) -> Decision:
    total = weighted_score(role, scores)
    fired = rescue_rules(role, scores, facts)

    # Rescue rules only stop a reject; they never block or downgrade ADVANCE
    # (Lavanya fires R2/R3 and still advances in the Section 6 calibration).
    if total >= ADVANCE_LINE and facts.g1_pass:
        route, reason = ADVANCE, "score >= 75 and G1 pass"
    elif total >= ADVANCE_LINE:
        route, reason = REVIEW, "G1 fail"
    elif total >= REJECT_LINE:
        route, reason = REVIEW, "band 55-74"
    elif fired:
        route, reason = REVIEW, "rescue " + "+".join(fired)
    else:
        route, reason = REJECT, "score < 55, no rescue rule"

    return Decision(
        role=role.key,
        scores=dict(scores),
        total=total,
        g1_pass=facts.g1_pass,
        route=route,
        reason=reason,
        rules_fired=fired,
        flags=flags(role, facts),
    )
