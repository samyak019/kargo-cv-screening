"""Backend for the hosted screening app (Vercel functions in api/).

Each scored CV is stored as one JSON record in Vercel Blob:
  candidates/<sha16>-<random>.json  ->  {id, file, sha, added, rows, evidence}
The sha is of the redacted CV text, so uploading the same CV again is a
no-op: it is never scored twice. The raw CV file is not stored.

Every endpoint needs the X-Access-Code header to match the ACCESS_CODE env
var. If ACCESS_CODE or ANTHROPIC_API_KEY is unset the API refuses to run, so
a public URL can't be used to read candidate data or spend API credit.
"""
import base64
import hmac
import json
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import report
import screen
from rubric import ROLES

PREFIX = "candidates/"
MAX_UPLOAD_BYTES = 3 * 1024 * 1024  # base64 must fit Vercel's 4.5 MB body limit


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def check_access(code: Optional[str]) -> None:
    expected = os.environ.get("ACCESS_CODE", "")
    if not expected:
        raise ApiError(503, "ACCESS_CODE is not set on the server. Add it in Vercel → Settings → "
                            "Environment Variables, then redeploy.")
    if not code or not hmac.compare_digest(code.encode(), expected.encode()):
        raise ApiError(401, "Wrong or missing access code.")


# ------------------------------------------------------------- blob store

def _blob():
    from vercel import blob  # imported lazily: needs Python 3.10+ (present on Vercel)

    if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        raise ApiError(503, "No Blob store is connected to this project (BLOB_READ_WRITE_TOKEN missing).")
    return blob


def list_records() -> List[dict]:
    blob = _blob()
    items, cursor = [], None
    while True:
        page = blob.list_objects(prefix=PREFIX, cursor=cursor, limit=1000)
        items.extend(page.blobs)
        if not page.has_more:
            break
        cursor = page.cursor
    records = []
    for item in items:
        try:
            rec = json.loads(blob.get(item.url))
        except Exception:  # one bad record shouldn't hide the rest
            continue
        rec["_url"] = item.url
        records.append(rec)
    return records


def find_by_sha(sha: str) -> Optional[dict]:
    blob = _blob()
    page = blob.list_objects(prefix=f"{PREFIX}{sha[:16]}", limit=10)
    for item in page.blobs:
        rec = json.loads(blob.get(item.url))
        if rec.get("sha") == sha:
            return rec
    return None


def save_record(rec: dict) -> None:
    _blob().put(f"{PREFIX}{rec['id']}.json", json.dumps(rec, ensure_ascii=False).encode("utf-8"),
                content_type="application/json", add_random_suffix=True)


def delete_record(record_id: str) -> bool:
    blob = _blob()
    page = blob.list_objects(prefix=f"{PREFIX}{record_id}", limit=10)
    urls = [b.url for b in page.blobs]
    if urls:
        blob.delete(urls)
    return bool(urls)


# ------------------------------------------------------------- endpoints

def payload_from_records(records: List[dict]) -> dict:
    """Same shape as report.html's embedded data, so the page renders it as-is."""
    rows, evidence = [], {}
    for rec in records:
        for row in rec.get("rows", []):
            rows.append({**row, "file": rec["id"], "display_file": rec.get("file", "")})
        evidence[rec["id"]] = rec.get("evidence", {})
    data = report.build_data(rows, evidence)
    added = {rec["id"]: rec.get("added", "") for rec in records}
    names = {rec["id"]: rec.get("file", "") for rec in records}
    for c in data:
        c["id"], c["added"], c["file"] = c["file"], added.get(c["file"], ""), names.get(c["file"], "")
    return report.page_payload(data)


def get_candidates() -> dict:
    return payload_from_records(list_records())


def score_upload(body: dict, client=None, model: Optional[str] = None) -> Tuple[int, dict]:
    filename = str(body.get("filename") or "").strip()
    if not filename.lower().endswith((".docx", ".pdf")):
        raise ApiError(400, "Upload a .docx or .pdf file.")
    try:
        data = base64.b64decode(body.get("data") or "", validate=True)
    except Exception:
        raise ApiError(400, "File data is not valid base64.")
    if not data:
        raise ApiError(400, "The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "File is over 3 MB.")

    try:
        text = screen.extract_text_bytes(filename, data)
    except Exception as e:
        raise ApiError(422, f"Couldn't read this file: {e}")
    if len(text.strip()) < 50:
        raise ApiError(422, "No readable text in this file (is it a scanned image?). "
                            "Export it as a text PDF or .docx and try again.")

    sha = screen.text_sha(screen.redact(text))
    existing = find_by_sha(sha)
    if existing:
        return 200, {"status": "exists", "id": existing["id"], "file": existing.get("file", filename),
                     "message": "Already scored. Kept the existing result."}

    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ApiError(503, "ANTHROPIC_API_KEY is not set on the server.")
        import anthropic

        client = anthropic.Anthropic()
    model = model or os.environ.get("KARGO_MODEL", screen.DEFAULT_MODEL)
    rows, file_ev = screen.score_cv(client, model, filename, text, list(ROLES.values()),
                                    log=lambda *_: None)

    model_errors = [r["error"] for r in rows if r.get("route_reason") == "model error"]
    if model_errors:  # don't store a half-scored CV; let the user retry
        raise ApiError(502, "Scoring failed, nothing was saved. Try again. (" + model_errors[0][:200] + ")")

    record = {"id": sha[:16], "file": filename, "sha": sha,
              "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "model": model, "rows": rows, "evidence": file_ev}
    save_record(record)
    return 201, {"status": "scored", "id": record["id"], "file": filename,
                 "summary": {r["role"]: {"total": r.get("total"), "route": r["route"]} for r in rows}}
