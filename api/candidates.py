"""GET /api/candidates -> all scored candidates.  DELETE /api/candidates?id=<id> -> remove one."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapp  # noqa: E402
from webhttp import JsonHandler  # noqa: E402


class handler(JsonHandler):
    def do_GET(self):
        self.run(lambda: (200, webapp.get_candidates()))

    def do_DELETE(self):
        def remove():
            rid = self.query().get("id", "")
            if not rid.isalnum():
                raise webapp.ApiError(400, "Missing or invalid id.")
            if not webapp.delete_record(rid):
                raise webapp.ApiError(404, "No candidate with that id.")
            return 200, {"status": "deleted", "id": rid}
        self.run(remove)
