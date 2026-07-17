"""Threaded in-process mock of the DynBench backend for end-to-end tests.

Serves the three routes the frontend talks to:
  GET  …/health     — healthcheck probe
  GET  …/v1/models  — model list for the sidebar/API
  POST …            — transform: echoes the pair back with a "MOCKED " prefix
                      plus a plausible selected_replace block
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

MOCK_PREFIX = "MOCKED "


class _Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/health"):
            self._json({"status": "ok"})
        elif self.path.endswith("/v1/models"):
            self._json({"models": ["mock/model-a"]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length))
        self._json({
            "transformed_question": MOCK_PREFIX + req.get("question", ""),
            "transformed_query": MOCK_PREFIX + req.get("query", ""),
            "selected_replace": {
                "old_entity": "wd:Q131436", "old_label": "boardgame",
                "new_entity": "wd:Q142714", "new_label": "card game",
                "old_pagerank": 130, "new_pagerank": 106,
            },
        })

    def log_message(self, *args):  # keep test output clean
        pass


def start() -> tuple[HTTPServer, str]:
    """Start the mock backend on a free port; returns (server, base_url)."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
