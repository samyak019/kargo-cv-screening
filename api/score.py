"""POST /api/score  {filename, data: base64}  -> scores a new CV for PM and SPM and stores it."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapp  # noqa: E402
from webhttp import JsonHandler  # noqa: E402


class handler(JsonHandler):
    def do_POST(self):
        self.run(lambda: webapp.score_upload(self.read_json()))
