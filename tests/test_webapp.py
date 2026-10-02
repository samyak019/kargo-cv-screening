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


def test_access_code_required(monkeypatch):
    monkeypatch.delenv("ACCESS_CODE", raising=False)
    with pytest.raises(webapp.ApiError) as e:
        webapp.check_access("anything")
    assert e.value.status == 503
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
