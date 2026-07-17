"""
Tests for healthcheck.py.

Streamlit's server module is mocked before healthcheck is imported so the
tests do not depend on a running Streamlit instance.
"""
import json
import sys
import unittest
from unittest.mock import MagicMock, patch

import requests
import tornado.testing
import tornado.web


# ---------------------------------------------------------------------------
# Isolate the module under test from Streamlit's server machinery.
# We mock the streamlit server module so that the _create_app patch in
# healthcheck.py binds against a harmless mock instead of the real class.
# ---------------------------------------------------------------------------

def _load_healthcheck_with_mocked_streamlit():
    """Import healthcheck with a fresh module state and mocked Streamlit."""
    # Remove any cached copy so we get a clean import each time
    for key in list(sys.modules):
        if key == "healthcheck" or key.startswith("healthcheck."):
            del sys.modules[key]

    mock_st_server = MagicMock()
    mock_st_server.Server._create_app = MagicMock(return_value=MagicMock())

    # Mock the full import chain — Python requires every parent package to exist
    with patch.dict(sys.modules, {
        "streamlit.web": MagicMock(),
        "streamlit.web.server": MagicMock(),
        "streamlit.web.server.server": mock_st_server,
    }):
        import healthcheck as hc  # noqa: PLC0415
    return hc


# Load once for the whole test session
hc = _load_healthcheck_with_mocked_streamlit()


# ---------------------------------------------------------------------------
# _derive_health_url
# ---------------------------------------------------------------------------

class TestDeriveHealthUrl(unittest.TestCase):

    def test_replaces_path_with_health(self):
        self.assertEqual(
            hc._derive_health_url("http://example.com:8080/transform"),
            "http://example.com:8080/health",
        )

    def test_strips_query_string(self):
        self.assertEqual(
            hc._derive_health_url("http://example.com:8080/transform?foo=bar"),
            "http://example.com:8080/health",
        )

    def test_strips_fragment(self):
        self.assertEqual(
            hc._derive_health_url("http://example.com:8080/transform#section"),
            "http://example.com:8080/health",
        )

    def test_preserves_host_and_port(self):
        url = hc._derive_health_url("http://demos.swe.htwk-leipzig.de:40128/transform")
        self.assertTrue(url.startswith("http://demos.swe.htwk-leipzig.de:40128/"))
        self.assertTrue(url.endswith("/health"))


# ---------------------------------------------------------------------------
# _probe
# ---------------------------------------------------------------------------

class TestProbe(unittest.TestCase):

    def test_returns_true_on_200(self):
        mock_response = MagicMock(status_code=200, text="healthy")
        with patch.object(hc.requests, "get", return_value=mock_response):
            ok, msg = hc._probe("http://example.com/health")
        self.assertTrue(ok)
        self.assertEqual(msg, "healthy")

    def test_returns_false_on_non_200(self):
        mock_response = MagicMock(status_code=503, text="Service Unavailable")
        with patch.object(hc.requests, "get", return_value=mock_response):
            ok, msg = hc._probe("http://example.com/health")
        self.assertFalse(ok)
        self.assertIn("503", msg)
        self.assertIn("Service Unavailable", msg)

    def test_returns_false_on_connection_error(self):
        with patch.object(
            hc.requests, "get", side_effect=requests.exceptions.ConnectionError("refused")
        ):
            ok, msg = hc._probe("http://example.com/health")
        self.assertFalse(ok)
        self.assertIn("refused", msg)

    def test_returns_false_on_timeout(self):
        with patch.object(
            hc.requests, "get", side_effect=requests.exceptions.Timeout()
        ):
            ok, msg = hc._probe("http://example.com/health")
        self.assertFalse(ok)

    def test_uses_five_second_timeout(self):
        mock_response = MagicMock(status_code=200, text="ok")
        with patch.object(hc.requests, "get", return_value=mock_response) as mock_get:
            hc._probe("http://example.com/health")
        mock_get.assert_called_once_with("http://example.com/health", timeout=5)


# ---------------------------------------------------------------------------
# get_status / shared state
# ---------------------------------------------------------------------------

class TestGetStatus(unittest.TestCase):

    def setUp(self):
        # Reset to a known state before each test
        with hc._lock:
            hc._status["ok"] = False
            hc._status["message"] = "Initializing"

    def test_returns_copy(self):
        status = hc.get_status()
        status["ok"] = True  # mutating the copy must not affect internal state
        self.assertFalse(hc._status["ok"])

    def test_reflects_updated_status(self):
        with hc._lock:
            hc._status["ok"] = True
            hc._status["message"] = "all good"
        status = hc.get_status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["message"], "all good")


# ---------------------------------------------------------------------------
# HealthHandler — tested via a minimal Tornado app (no Streamlit dependency)
# ---------------------------------------------------------------------------

class TestHealthHandlerOk(tornado.testing.AsyncHTTPTestCase):

    def get_app(self):
        return tornado.web.Application([(r"/health", hc.HealthHandler)])

    def setUp(self):
        super().setUp()
        with hc._lock:
            hc._status["ok"] = True
            hc._status["message"] = "all good"

    def test_get_returns_200(self):
        response = self.fetch("/health")
        self.assertEqual(response.code, 200)

    def test_get_returns_json_status_ok(self):
        response = self.fetch("/health")
        body = json.loads(response.body)
        self.assertEqual(body["status"], "ok")

    def test_content_type_is_json(self):
        response = self.fetch("/health")
        self.assertIn("application/json", response.headers["Content-Type"])

    def test_head_returns_200(self):
        response = self.fetch("/health", method="HEAD")
        self.assertEqual(response.code, 200)


class TestHealthHandlerUnavailable(tornado.testing.AsyncHTTPTestCase):

    def get_app(self):
        return tornado.web.Application([(r"/health", hc.HealthHandler)])

    def setUp(self):
        super().setUp()
        with hc._lock:
            hc._status["ok"] = False
            hc._status["message"] = "Connection refused"

    def test_get_returns_503(self):
        response = self.fetch("/health")
        self.assertEqual(response.code, 503)

    def test_get_returns_json_status_unavailable(self):
        response = self.fetch("/health")
        body = json.loads(response.body)
        self.assertEqual(body["status"], "unavailable")

    def test_error_message_is_included(self):
        response = self.fetch("/health")
        body = json.loads(response.body)
        self.assertEqual(body["message"], "Connection refused")

    def test_head_returns_503(self):
        response = self.fetch("/health", method="HEAD")
        self.assertEqual(response.code, 503)


# ---------------------------------------------------------------------------
# start_background_check
# ---------------------------------------------------------------------------

class TestStartBackgroundCheck(unittest.TestCase):

    def setUp(self):
        # Reset module-level thread guard and status before each test
        hc._background_thread = None
        with hc._lock:
            hc._status["ok"] = False
            hc._status["message"] = "Initializing"

    def tearDown(self):
        hc._background_thread = None

    def test_performs_immediate_probe_on_start(self):
        mock_response = MagicMock(status_code=200, text="healthy")
        with patch.object(hc.requests, "get", return_value=mock_response):
            hc.start_background_check("http://example.com:8080/transform")
        self.assertTrue(hc._status["ok"])
        self.assertEqual(hc._status["message"], "healthy")

    def test_starts_background_thread(self):
        with patch.object(hc.requests, "get", return_value=MagicMock(status_code=200, text="ok")):
            hc.start_background_check("http://example.com:8080/transform")
        self.assertIsNotNone(hc._background_thread)
        self.assertTrue(hc._background_thread.is_alive())

    def test_is_idempotent(self):
        with patch.object(hc.requests, "get", return_value=MagicMock(status_code=200, text="ok")):
            hc.start_background_check("http://example.com:8080/transform")
            first_thread = hc._background_thread
            hc.start_background_check("http://example.com:8080/transform")
        self.assertIs(hc._background_thread, first_thread)

    def test_probes_correct_health_url(self):
        with patch.object(hc.requests, "get", return_value=MagicMock(status_code=200, text="ok")) as mock_get:
            hc.start_background_check("http://example.com:8080/transform")
        mock_get.assert_called_with("http://example.com:8080/health", timeout=5)


if __name__ == "__main__":
    unittest.main()
