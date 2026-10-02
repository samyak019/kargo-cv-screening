"""GET /api/health -> whether scoring works right now (key checked with a model lookup, no generation)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webapp  # noqa: E402
from webhttp import JsonHandler  # noqa: E402


class handler(JsonHandler):
    def do_GET(self):
        self.run(lambda: (200, webapp.health()))
