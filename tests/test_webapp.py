import base64
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import report  # noqa: E402
import screen  # noqa: E402
import webapp  # noqa: E402
from rubric import ROLES  # noqa: E402


class FakeBlob:
    """In-memory stand-in for vercel.blob (list_objects / get / put / delete)."""

    def __init__(self):
        self.store = {}
        self.n = 0

    def put(self, path, body, content_type=None, add_random_suffix=False):
        self.n += 1
        path = path.replace(".json", f"-r{self.n}.json") if add_random_suffix else path
        self.store["https://blob/" + path] = body

    def list_objects(self, prefix="", cursor=None, limit=1000):
        blobs = [SimpleNamespace(url=u) for u in self.store if u[len("https://blob/"):].startswith(prefix)]
        return SimpleNamespace(blobs=blobs, has_more=False, cursor=None)

    def get(self, url):
        return self.store[url]

    def delete(self, urls):
        for u in urls:
            self.store.pop(u, None)


@pytest.fixture
def env(monkeypatch):
    fake = FakeBlob()
    calls = []

    def fake_assess(client, model, role, text):
        calls.append(role.key)
        if getattr(client, "fail", False):
            raise RuntimeError("model refused")
        crit = [screen.CriterionResult(id=c, score=3, evidence=["Ops executive at a customs house agent"],
                                       reason="r") for c in role.ids]
        return screen.Assessment(candidate_name="Asha Rao", criteria=crit, g1_pass=False, g1_quote="",
                                 pm_title_years=0, ops_tenure_years=3, ownership_role_years=2,
                                 mumbai_in_office_stated=False, mumbai_quote="", parse_confidence="high",
                                 brief="b")

    monkeypatch.setattr(webapp, "_blob", lambda: fake)
    monkeypatch.setattr(screen, "assess", fake_assess)
    monkeypatch.setenv("ACCESS_CODE", "s3cret")
    return SimpleNamespace(blob=fake, calls=calls)


def cv_b64(extra=""):
    import docx

    d = docx.Document()
    for line in ["Asha Rao | asha@x.com | +91 98202 11345",
                 "Ops executive at a customs house agent for 3 years. " + extra] + ["work"] * 60:
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return base64.b64encode(buf.getvalue()).decode()


def test_open_by_default_lockable_with_code(monkeypatch):
    monkeypatch.delenv("ACCESS_CODE", raising=False)
    webapp.check_access(None)  # public: no code needed
    monkeypatch.setenv("ACCESS_CODE", "s3cret")
    with pytest.raises(webapp.ApiError) as e:
        webapp.check_access("wrong")
    assert e.value.status == 401
    webapp.check_access("s3cret")


def test_score_store_dedupe_list_delete(env):
    status, body = webapp.score_upload({"filename": "asha.docx", "data": cv_b64()}, client=object(), model="m")
    assert status == 201 and body["status"] == "scored" and set(body["summary"]) == {"PM", "SPM"}
    assert sorted(env.calls) == ["PM", "SPM"]

    # same CV again: not scored twice
    env.calls.clear()
    status, body = webapp.score_upload({"filename": "renamed.docx", "data": cv_b64()}, client=object())
    assert body["status"] == "exists" and env.calls == []

    # contact details never stored
    stored = next(iter(env.blob.store.values())).decode()
    assert "asha@x.com" not in stored and "98202" not in stored

    payload = webapp.get_candidates()
    assert payload["api"] is False  # data payload; the page itself sets api mode
    (c,) = payload["candidates"]
    assert c["name"] == "Asha Rao" and c["file"] == "asha.docx" and c["id"]
    assert c["roles"]["PM"]["rank"] == 1 and c["roles"]["PM"]["criteria"][0]["evidence"]

    assert webapp.delete_record(c["id"]) and webapp.get_candidates()["candidates"] == []


def test_model_failure_saves_nothing(env):
    with pytest.raises(webapp.ApiError) as e:
        webapp.score_upload({"filename": "a.docx", "data": cv_b64()}, client=SimpleNamespace(fail=True))
    assert e.value.status == 502 and env.blob.store == {}


@pytest.mark.parametrize("body,status", [
    ({"filename": "a.txt", "data": "aGk="}, 400),
    ({"filename": "a.pdf", "data": "!!!"}, 400),
    ({"filename": "a.pdf", "data": ""}, 400),
    ({"filename": "a.pdf", "data": base64.b64encode(b"not a pdf").decode()}, 422),
])
def test_bad_uploads(env, body, status):
    with pytest.raises(webapp.ApiError) as e:
        webapp.score_upload(body, client=object())
    assert e.value.status == status


def test_public_index_is_current():
    expected = report.TEMPLATE.replace("__META__", "").replace(
        "__DATA__", report._embed(report.page_payload([], api=True)))
    assert (ROOT / "public" / "index.html").read_text() == expected, \
        "run: python report.py --app public/index.html"


# ------------------------------------------------------------- gemini path

class FakeGemini:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.models = self
        self.calls = 0

    def generate_content(self, model, contents, config):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def gemini_error(code, msg):
    from google.genai import errors
    return errors.APIError(code, {"error": {"code": code, "message": msg, "status": "X"}})


def sample_assessment():
    role = ROLES["PM"]
    crit = [screen.CriterionResult(id=c, score=2, evidence=["x"], reason="r") for c in role.ids]
    return screen.Assessment(candidate_name="A", criteria=crit, g1_pass=False, g1_quote="",
                             pm_title_years=0, ops_tenure_years=0, ownership_role_years=0,
                             mumbai_in_office_stated=False, mumbai_quote="", parse_confidence="high", brief="")


def test_gemini_parsed_and_json_fallback(monkeypatch):
    a = sample_assessment()
    ok = SimpleNamespace(parsed=a, text="", candidates=[])
    assert screen.assess(FakeGemini([ok]), "gemini-3.6-flash", ROLES["PM"], "cv") == a
    raw = SimpleNamespace(parsed=None, text=a.model_dump_json(), candidates=[])
    assert screen.assess(FakeGemini([raw]), "gemini-3.6-flash", ROLES["PM"], "cv").candidate_name == "A"
    bad = SimpleNamespace(parsed=None, text="not json", candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")])
    with pytest.raises(screen.ModelError, match="MAX_TOKENS"):
        screen.assess(FakeGemini([bad]), "gemini-3.6-flash", ROLES["PM"], "cv")


def test_gemini_retries_transient_then_succeeds(monkeypatch):
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    ok = SimpleNamespace(parsed=sample_assessment(), text="", candidates=[])
    fake = FakeGemini([gemini_error(503, "overloaded"), gemini_error(429, "per minute, retry in 2s"), ok])
    assert screen.assess(fake, "gemini-3.6-flash", ROLES["PM"], "cv").candidate_name == "A"
    assert fake.calls == 3


def test_gemini_daily_quota_and_bad_key_fail_fast():
    with pytest.raises(screen.ModelError, match="daily free-tier"):
        screen.assess(FakeGemini([gemini_error(429, "GenerateRequestsPerDayPerProject")]),
                      "gemini-3.6-flash", ROLES["PM"], "cv")
    fake = FakeGemini([gemini_error(400, "API key not valid")])
    with pytest.raises(screen.ModelError, match="400"):
        screen.assess(fake, "gemini-3.6-flash", ROLES["PM"], "cv")
    assert fake.calls == 1


def test_make_client_prefers_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    _, model = screen.make_client()
    assert model == screen.DEFAULT_GEMINI_MODEL
    monkeypatch.delenv("GEMINI_API_KEY")
    _, model = screen.make_client()
    assert model == screen.DEFAULT_MODEL
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(screen.ModelError):
        screen.make_client()


def test_vertex_express_key_detected(monkeypatch):
    monkeypatch.delenv("GEMINI_VERTEX", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.fake-express-key")
    client, _ = screen.make_client()
    assert "aiplatform.googleapis.com" in client._api_client._http_options.base_url
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFakeStudioKey")
    client, _ = screen.make_client()
    assert "generativelanguage.googleapis.com" in client._api_client._http_options.base_url
    monkeypatch.setenv("GEMINI_VERTEX", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.fake-express-key")
    client, _ = screen.make_client()
    assert "generativelanguage.googleapis.com" in client._api_client._http_options.base_url
