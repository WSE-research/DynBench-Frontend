"""
Tests for api.py — the POST /api/transform endpoint.

Streamlit's server module is mocked so the tests run without a live
Streamlit instance.  The DynBench backend is also mocked so no real
HTTP requests are made.
"""
import importlib
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import tornado.testing
import tornado.web


# ---------------------------------------------------------------------------
# Load api.py with all external dependencies mocked
# ---------------------------------------------------------------------------

def _load_api_with_mocks():
    """Import api with fresh module state, mocked Streamlit and environment."""
    for key in list(sys.modules):
        if key in ("api",) or key.startswith("api."):
            del sys.modules[key]

    mock_st_server = MagicMock()
    env = {"DYNBENCH": "http://mock-backend:1234/transform", "MODEL": "mock-model"}

    with patch.dict(sys.modules, {
        "streamlit.web": MagicMock(),
        "streamlit.web.server": MagicMock(),
        "streamlit.web.server.server": mock_st_server,
    }), patch.dict(os.environ, env):
        import api as _api  # noqa: PLC0415

    # patch.dict restores sys.modules on exit and removes the freshly imported
    # module.  Re-register it so that patch.object and any internal imports
    # resolve to the same object.
    sys.modules["api"] = _api
    return _api


_api = _load_api_with_mocks()


# ---------------------------------------------------------------------------
# OpenApiSpecHandler — GET /api/openapi.json
# ---------------------------------------------------------------------------

class TestOpenApiSpecHandler(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        return tornado.web.Application([
            (r"/api/openapi\.json", _api.OpenApiSpecHandler),
        ])

    def test_returns_200(self):
        resp = self.fetch("/api/openapi.json")
        self.assertEqual(resp.code, 200)

    def test_content_type_is_json(self):
        resp = self.fetch("/api/openapi.json")
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))

    def test_spec_is_valid_json(self):
        resp = self.fetch("/api/openapi.json")
        spec = json.loads(resp.body)
        self.assertIsInstance(spec, dict)

    def test_spec_contains_openapi_version(self):
        resp = self.fetch("/api/openapi.json")
        spec = json.loads(resp.body)
        self.assertEqual(spec["openapi"], "3.0.0")

    def test_spec_contains_transform_path(self):
        resp = self.fetch("/api/openapi.json")
        spec = json.loads(resp.body)
        self.assertIn("/api/transform", spec["paths"])

    def test_spec_transform_has_post_operation(self):
        resp = self.fetch("/api/openapi.json")
        spec = json.loads(resp.body)
        self.assertIn("post", spec["paths"]["/api/transform"])


# ---------------------------------------------------------------------------
# ApiRootHandler — GET /api redirects to /api/transform
# ---------------------------------------------------------------------------

class TestApiRootHandler(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        return tornado.web.Application([
            (r"/api", _api.ApiRootHandler),
            (r"/api/transform", _api.TransformHandler),
        ])

    def test_get_returns_302(self):
        resp = self.fetch("/api", follow_redirects=False)
        self.assertEqual(resp.code, 302)

    def test_redirect_target_is_api_transform(self):
        resp = self.fetch("/api", follow_redirects=False)
        self.assertEqual(resp.headers.get("Location"), "/api/transform")

    def test_following_redirect_reaches_swagger_ui(self):
        resp = self.fetch("/api", follow_redirects=True)
        self.assertEqual(resp.code, 200)
        self.assertIn(b"swagger-ui", resp.body)


# ---------------------------------------------------------------------------
# XSRF — all API handlers must opt out so plain curl / REST clients work
# ---------------------------------------------------------------------------

class TestXsrfDisabled(tornado.testing.AsyncHTTPTestCase):
    """Verify that POST /api/transform is not blocked by XSRF protection.

    Tornado raises 403 for POST requests when xsrf_cookies is enabled and the
    request carries no _xsrf token.  Each handler must set
    ``check_xsrf_cookie = False`` to opt out.
    """

    def get_app(self):
        # Enable xsrf_cookies at the application level to replicate the
        # Streamlit production configuration.
        return tornado.web.Application(
            [(r"/api/transform", _api.TransformHandler)],
            xsrf_cookies=True,
        )

    def test_post_without_xsrf_token_is_not_forbidden(self):
        payload = json.dumps({
            "question": "What is the capital of France?",
            "query": "SELECT ?uri WHERE { ?uri wdt:P31 wd:Q5119 }",
            "model": "gpt-4o",
        }).encode()
        resp = self.fetch(
            "/api/transform",
            method="POST",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        self.assertNotEqual(resp.code, 403, "POST was rejected with 403 — XSRF check not disabled")

    def test_check_xsrf_cookie_is_overridden_on_transform_handler(self):
        self.assertTrue(callable(_api.TransformHandler.check_xsrf_cookie))
        # The override must be a no-op (not raise)
        _api.TransformHandler.check_xsrf_cookie(object.__new__(_api.TransformHandler))

    def test_check_xsrf_cookie_is_overridden_on_models_handler(self):
        self.assertTrue(callable(_api.ModelsHandler.check_xsrf_cookie))

    def test_check_xsrf_cookie_is_overridden_on_openapi_spec_handler(self):
        self.assertTrue(callable(_api.OpenApiSpecHandler.check_xsrf_cookie))

    def test_check_xsrf_cookie_is_overridden_on_api_root_handler(self):
        self.assertTrue(callable(_api.ApiRootHandler.check_xsrf_cookie))


# ---------------------------------------------------------------------------
# TransformHandler GET — Swagger UI
# ---------------------------------------------------------------------------

class TestTransformHandlerSwaggerUi(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        return tornado.web.Application([
            (r"/api/transform", _api.TransformHandler),
        ])

    def test_get_returns_200(self):
        resp = self.fetch("/api/transform")
        self.assertEqual(resp.code, 200)

    def test_content_type_is_html(self):
        resp = self.fetch("/api/transform")
        self.assertIn("text/html", resp.headers.get("Content-Type", ""))

    def test_response_contains_swagger_ui(self):
        resp = self.fetch("/api/transform")
        self.assertIn(b"swagger-ui", resp.body)

    def test_response_references_openapi_spec(self):
        resp = self.fetch("/api/transform")
        self.assertIn(b"/api/openapi.json", resp.body)


# ---------------------------------------------------------------------------
# TransformHandler — bad requests (no backend call required)
# ---------------------------------------------------------------------------

class TestTransformHandlerBadRequest(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        return tornado.web.Application([
            (r"/api/transform", _api.TransformHandler),
        ])

    def test_non_json_body_returns_400(self):
        resp = self.fetch("/api/transform", method="POST", body="not json",
                          headers={"Content-Type": "application/json"})
        self.assertEqual(resp.code, 400)
        body = json.loads(resp.body)
        self.assertIn("error", body)
        self.assertIn("Invalid JSON", body["error"])

    def test_missing_question_returns_400(self):
        payload = json.dumps({"query": "SELECT ?x WHERE { ?x ?y ?z }", "model": "gpt-4o"})
        resp = self.fetch("/api/transform", method="POST", body=payload,
                          headers={"Content-Type": "application/json"})
        self.assertEqual(resp.code, 400)
        body = json.loads(resp.body)
        self.assertIn("question", body["error"])

    def test_missing_query_returns_400(self):
        payload = json.dumps({"question": "Who is the tallest?", "model": "gpt-4o"})
        resp = self.fetch("/api/transform", method="POST", body=payload,
                          headers={"Content-Type": "application/json"})
        self.assertEqual(resp.code, 400)
        body = json.loads(resp.body)
        self.assertIn("query", body["error"])

    def test_missing_model_returns_400(self):
        payload = json.dumps({"question": "Who is the tallest?", "query": "SELECT ?x WHERE { ?x ?y ?z }"})
        resp = self.fetch("/api/transform", method="POST", body=payload,
                          headers={"Content-Type": "application/json"})
        self.assertEqual(resp.code, 400)
        body = json.loads(resp.body)
        self.assertIn("model", body["error"])

    def test_all_required_missing_returns_400(self):
        resp = self.fetch("/api/transform", method="POST", body="{}",
                          headers={"Content-Type": "application/json"})
        self.assertEqual(resp.code, 400)

    def test_whitespace_only_fields_treated_as_missing(self):
        payload = json.dumps({"question": "   ", "query": "\t\n", "model": "  "})
        resp = self.fetch("/api/transform", method="POST", body=payload,
                          headers={"Content-Type": "application/json"})
        self.assertEqual(resp.code, 400)

    def test_content_type_is_json(self):
        resp = self.fetch("/api/transform", method="POST", body="{}",
                          headers={"Content-Type": "application/json"})
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))


# ---------------------------------------------------------------------------
# TransformHandler — backend success
# ---------------------------------------------------------------------------

_BACKEND_SUCCESS = {
    "transformed_question": "What is the capital of France?",
    "transformed_query": "SELECT ?x WHERE { ?x wdt:P31 wd:Q36 }",
}

_VALID_PAYLOAD = json.dumps({
    "question": "What is the highest mountain?",
    "query": "SELECT ?x WHERE { ?x wdt:P31 wd:Q8502 }",
    "model": "gpt-4o",
})


class TestTransformHandlerSuccess(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        return tornado.web.Application([
            (r"/api/transform", _api.TransformHandler),
        ])

    def test_returns_200_on_backend_success(self):
        with patch.object(_api, "call_dynbench", return_value=(_BACKEND_SUCCESS, None)):
            resp = self.fetch("/api/transform", method="POST", body=_VALID_PAYLOAD,
                              headers={"Content-Type": "application/json"})
        self.assertEqual(resp.code, 200)

    def test_response_contains_transformed_fields(self):
        with patch.object(_api, "call_dynbench", return_value=(_BACKEND_SUCCESS, None)):
            resp = self.fetch("/api/transform", method="POST", body=_VALID_PAYLOAD,
                              headers={"Content-Type": "application/json"})
        body = json.loads(resp.body)
        self.assertEqual(body["transformed_question"], _BACKEND_SUCCESS["transformed_question"])
        self.assertEqual(body["transformed_query"], _BACKEND_SUCCESS["transformed_query"])

    def test_passes_model_to_backend(self):
        with patch.object(_api, "call_dynbench", return_value=(_BACKEND_SUCCESS, None)) as mock:
            self.fetch("/api/transform", method="POST", body=_VALID_PAYLOAD,
                       headers={"Content-Type": "application/json"})
        args = mock.call_args.args
        self.assertEqual(args[3], "gpt-4o")  # model

    def test_passes_complexity_and_language_to_backend(self):
        payload = json.dumps({
            "question": "Who invented the telephone?",
            "query": "SELECT ?x WHERE { ?x wdt:P31 wd:Q1 }",
            "model": "gpt-4o",
            "complexity": "hard",
            "language": "de",
        })
        with patch.object(_api, "call_dynbench", return_value=(_BACKEND_SUCCESS, None)) as mock:
            self.fetch("/api/transform", method="POST", body=payload,
                       headers={"Content-Type": "application/json"})
        args = mock.call_args.args
        self.assertEqual(args[4], "hard")    # complexity
        self.assertEqual(args[5], "de")      # language

    def test_defaults_complexity_and_language(self):
        with patch.object(_api, "call_dynbench", return_value=(_BACKEND_SUCCESS, None)) as mock:
            self.fetch("/api/transform", method="POST", body=_VALID_PAYLOAD,
                       headers={"Content-Type": "application/json"})
        args = mock.call_args.args
        self.assertEqual(args[4], "normal")
        self.assertEqual(args[5], "en")


# ---------------------------------------------------------------------------
# TransformHandler — backend failure
# ---------------------------------------------------------------------------

class TestTransformHandlerBackendError(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        return tornado.web.Application([
            (r"/api/transform", _api.TransformHandler),
        ])

    def test_returns_500_on_backend_error(self):
        with patch.object(_api, "call_dynbench", return_value=(None, "Connection refused")):
            resp = self.fetch("/api/transform", method="POST", body=_VALID_PAYLOAD,
                              headers={"Content-Type": "application/json"})
        self.assertEqual(resp.code, 500)

    def test_error_message_is_included(self):
        with patch.object(_api, "call_dynbench", return_value=(None, "HTTP 503: Service Unavailable")):
            resp = self.fetch("/api/transform", method="POST", body=_VALID_PAYLOAD,
                              headers={"Content-Type": "application/json"})
        body = json.loads(resp.body)
        self.assertIn("HTTP 503", body["error"])


# ---------------------------------------------------------------------------
# ModelsHandler — GET /api/models
# ---------------------------------------------------------------------------

class TestModelsHandler(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        return tornado.web.Application([
            (r"/api/models", _api.ModelsHandler),
        ])

    def test_returns_200(self):
        resp = self.fetch("/api/models")
        self.assertEqual(resp.code, 200)

    def test_content_type_is_json(self):
        resp = self.fetch("/api/models")
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))

    def test_response_is_a_list(self):
        resp = self.fetch("/api/models")
        body = json.loads(resp.body)
        self.assertIsInstance(body, list)

    def test_response_is_non_empty(self):
        resp = self.fetch("/api/models")
        body = json.loads(resp.body)
        self.assertGreater(len(body), 0)

    def test_returns_model_from_env(self):
        # _AVAILABLE_MODELS was seeded from env at import time; verify at least
        # one entry matches the mock-model set in _load_api_with_mocks().
        resp = self.fetch("/api/models")
        body = json.loads(resp.body)
        self.assertIn("mock-model", body)

    def test_returns_multiple_models_when_models_env_set(self):
        with patch.object(_api, "_AVAILABLE_MODELS", ["gpt-4o", "gpt-3.5-turbo"]):
            resp = self.fetch("/api/models")
        self.assertEqual(json.loads(resp.body), ["gpt-4o", "gpt-3.5-turbo"])

    def test_available_models_parsed_from_comma_separated_env(self):
        with patch.dict(os.environ, {"MODELS": "gpt-4o, gpt-3.5-turbo, llama3"}):
            models = [
                m.strip()
                for m in os.environ["MODELS"].split(",")
                if m.strip()
            ]
        self.assertEqual(models, ["gpt-4o", "gpt-3.5-turbo", "llama3"])

    def test_available_models_falls_back_to_model_env(self):
        # When MODELS is absent, _AVAILABLE_MODELS should equal [MODEL].
        with patch.object(_api, "_AVAILABLE_MODELS", ["mock-model"]):
            resp = self.fetch("/api/models")
        self.assertEqual(json.loads(resp.body), ["mock-model"])


if __name__ == "__main__":
    unittest.main()
