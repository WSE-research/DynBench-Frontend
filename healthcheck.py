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


# Patch start_listening to inject our /health route.
#
# Server.start() calls start_listening(app) as an unqualified module-level
# name, so Python resolves it from _st_server.__dict__ at call time.
# Replacing the name here therefore intercepts the call regardless of which
# code path builds the app — and we receive the fully-constructed Application
# object directly, which is simpler and more reliable than patching _create_app.
#
# Requirement: healthcheck must be imported before bootstrap.run() so the
# patch is in place before Server.start() is executed.  Use run.py as the
# entry point instead of `streamlit run app.py`.
_original_start_listening = _st_server.start_listening


def _patched_start_listening(app: "tornado.web.Application") -> None:  # type: ignore[name-defined]
    # In Tornado 6.4+ handlers live in app.wildcard_router.rules.
    # Prepend our route so it is matched before the catch-all static-file handler.
    app.wildcard_router.rules.insert(0, Rule(PathMatches(r"/health"), HealthHandler))
    logger.info("Registered /health endpoint on Streamlit's Tornado server")
    _original_start_listening(app)


_st_server.start_listening = _patched_start_listening
