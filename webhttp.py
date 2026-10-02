"""Tiny JSON helpers for the Vercel Python functions in api/."""
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import webapp  # noqa: E402


class JsonHandler(BaseHTTPRequestHandler):
    def send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 4_600_000:
            raise webapp.ApiError(413, "Upload too large.")
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise webapp.ApiError(400, "Body must be JSON.")

    def query(self) -> dict:
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def run(self, fn) -> None:
        try:
            webapp.check_access(self.headers.get("X-Access-Code"))
            status, body = fn()
            self.send_json(status, body)
        except webapp.ApiError as e:
            self.send_json(e.status, {"error": e.message, "code": e.code})
        except Exception as e:  # keep details in the function log, not the response
            traceback.print_exc()
            self.send_json(500, {"error": f"Server error: {type(e).__name__}"})
