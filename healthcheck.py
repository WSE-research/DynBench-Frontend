import json
import logging
import threading
import time
from urllib.parse import urlparse, urlunparse

import requests
from tornado.web import RequestHandler
from tornado.routing import Rule, PathMatches
import streamlit.web.server.server as _st_server

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_status: dict = {"ok": False, "message": "Initializing"}
_background_thread: threading.Thread | None = None

HEALTH_CHECK_INTERVAL = 30  # seconds between backend polls


def _derive_health_url(dynbench_url: str) -> str:
    parsed = urlparse(dynbench_url)
    return urlunparse(parsed._replace(path="/health", query="", fragment=""))


def _probe(health_url: str) -> tuple[bool, str]:
    """Probe the backend health URL. Returns (ok, message)."""
    try:
        r = requests.get(health_url, timeout=5)
        if r.status_code == 200:
            return True, r.text.strip()
        return False, f"HTTP {r.status_code}: {r.text.strip()}"
    except requests.exceptions.RequestException as e:
        return False, str(e)


def _poll(health_url: str) -> None:
    """Background daemon: probe backend repeatedly and update shared status."""
    while True:
        ok, message = _probe(health_url)
        with _lock:
            _status["ok"] = ok
            _status["message"] = message
        if ok:
            logger.info("Backend health OK: %s", message)
        else:
            logger.warning("Backend health FAIL: %s", message)
        time.sleep(HEALTH_CHECK_INTERVAL)


def start_background_check(dynbench_url: str) -> None:
    """Start a daemon thread that polls the DynBench backend health endpoint.

    Safe to call multiple times — only one thread is ever started.
    Does an immediate synchronous probe first so the status is populated
    before any request hits the /health endpoint.
    """
    global _background_thread
    if _background_thread is not None:
        return

    health_url = _derive_health_url(dynbench_url)
    logger.info("Starting background health check against %s", health_url)

    # Immediate first probe so the status is correct from the first request
    ok, message = _probe(health_url)
    with _lock:
        _status["ok"] = ok
        _status["message"] = message

    _background_thread = threading.Thread(
        target=_poll, args=(health_url,), daemon=True, name="dynbench-health-poller"
    )
    _background_thread.start()


def get_status() -> dict:
    with _lock:
        return _status.copy()


class HealthHandler(RequestHandler):
    async def get(self) -> None:
        await self._respond()

    async def head(self) -> None:
        await self._respond()

    async def _respond(self) -> None:
        status = get_status()
        self.set_header("Content-Type", "application/json")
        if status["ok"]:
            self.set_status(200)
            self.write(json.dumps({"status": "ok"}))
        else:
            self.set_status(503)
            self.write(
                json.dumps({"status": "unavailable", "message": status["message"]})
            )


# Patch Server._create_app to inject our /health route.
# This must be imported before bootstrap.run() is called so the patch is in
# place when the Server instance first calls _create_app during startup.
_original_create_app = _st_server.Server._create_app


def _patched_create_app(self):  # type: ignore[override]
    app = _original_create_app(self)
    # In Tornado 6.4+ handlers are stored in app.wildcard_router.rules.
    # Prepend our route so it is matched before the catch-all static-file handler.
    app.wildcard_router.rules.insert(0, Rule(PathMatches(r"/health"), HealthHandler))
    logger.info("Registered /health endpoint on Streamlit's Tornado server")
    return app


_st_server.Server._create_app = _patched_create_app
