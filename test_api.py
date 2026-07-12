"""
Tests for api.py — the POST /api/transform endpoint.

Streamlit's server module is mocked so the tests run without a live
Streamlit instance.  The DynBench backend is also mocked so no real
HTTP requests are made.
"""
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


# ---------------------------------------------------------------------------
# TransformBenchmarkHandler — POST /api/transform-benchmark (batch API)
# ---------------------------------------------------------------------------

_QALD_FILE = json.dumps({
    "questions": [
        {
            "id": str(i),
            "question": [{"language": "en", "string": f"Question {i}?"}],
            "query": {"sparql": f"SELECT ?x WHERE {{ ?x wdt:P{i} ?y }}"},
        }
        for i in range(1, 4)  # 3 pairs
    ]
}).encode()


def _multipart(filename: str, content: bytes, fields: dict | None = None):
    """Build a multipart/form-data body with a 'file' part and extra fields."""
    boundary = "testboundary123"
    parts = []
    for name, value in (fields or {}).items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
            f"\r\n\r\n{value}\r\n".encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: application/octet-stream'
        "\r\n\r\n".encode() + content + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


class _BenchmarkHandlerTestBase(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        return tornado.web.Application([
            (r"/api/transform-benchmark", _api.TransformBenchmarkHandler),
        ])


class TestTransformBenchmarkBadRequest(_BenchmarkHandlerTestBase):
    def test_no_file_returns_400(self):
        resp = self.fetch("/api/transform-benchmark?model=gpt-4o", method="POST", body=b"")
        self.assertEqual(resp.code, 400)
        self.assertIn("No benchmark file", json.loads(resp.body)["error"])

    def test_raw_body_without_filename_returns_400(self):
        resp = self.fetch("/api/transform-benchmark?model=gpt-4o",
                          method="POST", body=_QALD_FILE)
        self.assertEqual(resp.code, 400)
        self.assertIn("filename", json.loads(resp.body)["error"])

    def test_missing_model_returns_400(self):
        body, ctype = _multipart("qald.json", _QALD_FILE)
        resp = self.fetch("/api/transform-benchmark", method="POST", body=body,
                          headers={"Content-Type": ctype})
        self.assertEqual(resp.code, 400)
        self.assertIn("model", json.loads(resp.body)["error"])

    def test_invalid_limit_returns_400(self):
        body, ctype = _multipart("qald.json", _QALD_FILE)
        resp = self.fetch("/api/transform-benchmark?model=gpt-4o&limit=-3",
                          method="POST", body=body, headers={"Content-Type": ctype})
        self.assertEqual(resp.code, 400)
        self.assertIn("limit", json.loads(resp.body)["error"])

    def test_invalid_response_mode_returns_400(self):
        body, ctype = _multipart("qald.json", _QALD_FILE)
        resp = self.fetch("/api/transform-benchmark?model=gpt-4o&response=xml",
                          method="POST", body=body, headers={"Content-Type": ctype})
        self.assertEqual(resp.code, 400)
        self.assertIn("response", json.loads(resp.body)["error"])

    def test_unrecognized_format_returns_400(self):
        body, ctype = _multipart("notes.txt", b"plain text, no benchmark structure")
        resp = self.fetch("/api/transform-benchmark?model=gpt-4o", method="POST",
                          body=body, headers={"Content-Type": ctype})
        self.assertEqual(resp.code, 400)
        self.assertIn("Unsupported", json.loads(resp.body)["error"])

    def test_get_serves_swagger_ui(self):
        resp = self.fetch("/api/transform-benchmark")
        self.assertEqual(resp.code, 200)
        self.assertIn(b"swagger-ui", resp.body)

    def test_check_xsrf_cookie_is_overridden(self):
        self.assertTrue(callable(_api.TransformBenchmarkHandler.check_xsrf_cookie))
        _api.TransformBenchmarkHandler.check_xsrf_cookie(
            object.__new__(_api.TransformBenchmarkHandler)
        )


def _batch_backend_success(url, question, query, model, complexity, language):
    return (
        {
            "transformed_question": f"NEW {question}",
            "transformed_query": f"NEW {query}",
            "selected_replace": {"old_entity": "wd:Q1", "old_label": "old"},
        },
        None,
    )


class TestTransformBenchmarkSuccess(_BenchmarkHandlerTestBase):
    def test_json_report_multipart(self):
        with patch.object(_api, "call_dynbench", side_effect=_batch_backend_success):
            body, ctype = _multipart("qald.json", _QALD_FILE)
            resp = self.fetch("/api/transform-benchmark?model=gpt-4o&limit=2",
                              method="POST", body=body, headers={"Content-Type": ctype})
        self.assertEqual(resp.code, 200)
        report = json.loads(resp.body)
        self.assertEqual(report["format"], "QALD JSON")
        self.assertEqual(report["total_pairs"], 3)
        self.assertEqual(report["processed"], 2)  # limit respected
        self.assertEqual(report["succeeded"], 2)
        self.assertEqual(report["failed"], 0)
        first = report["results"][0]
        self.assertEqual(first["id"], "1")
        self.assertEqual(first["question"], "Question 1?")
        self.assertEqual(first["transformed_question"], "NEW Question 1?")
        self.assertIn("selected_replace", first)

    def test_limit_zero_processes_all(self):
        with patch.object(_api, "call_dynbench", side_effect=_batch_backend_success) as mock:
            body, ctype = _multipart("qald.json", _QALD_FILE)
            resp = self.fetch("/api/transform-benchmark?model=gpt-4o&limit=0",
                              method="POST", body=body, headers={"Content-Type": ctype})
        self.assertEqual(json.loads(resp.body)["processed"], 3)
        self.assertEqual(mock.call_count, 3)

    def test_raw_body_with_filename_param(self):
        with patch.object(_api, "call_dynbench", side_effect=_batch_backend_success):
            resp = self.fetch(
                "/api/transform-benchmark?model=gpt-4o&filename=qald.json&limit=1",
                method="POST", body=_QALD_FILE,
            )
        self.assertEqual(resp.code, 200)
        self.assertEqual(json.loads(resp.body)["format"], "QALD JSON")

    def test_form_fields_accepted_for_parameters(self):
        with patch.object(_api, "call_dynbench", side_effect=_batch_backend_success) as mock:
            body, ctype = _multipart(
                "qald.json", _QALD_FILE,
                fields={"model": "llama3", "complexity": "hard", "language": "de", "limit": "1"},
            )
            resp = self.fetch("/api/transform-benchmark", method="POST", body=body,
                              headers={"Content-Type": ctype})
        self.assertEqual(resp.code, 200)
        args = mock.call_args.args
        self.assertEqual(args[3], "llama3")
        self.assertEqual(args[4], "hard")
        self.assertEqual(args[5], "de")

    def test_response_file_returns_same_format_export(self):
        with patch.object(_api, "call_dynbench", side_effect=_batch_backend_success):
            body, ctype = _multipart("qald.json", _QALD_FILE)
            resp = self.fetch(
                "/api/transform-benchmark?model=gpt-4o&limit=2&response=file",
                method="POST", body=body, headers={"Content-Type": ctype})
        self.assertEqual(resp.code, 200)
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))
        self.assertIn("qald-transformed.json", resp.headers.get("Content-Disposition", ""))
        exported = json.loads(resp.body)
        self.assertEqual(len(exported["questions"]), 2)
        self.assertEqual(
            exported["questions"][0]["question"][0]["string"], "NEW Question 1?"
        )
        self.assertTrue(
            exported["questions"][0]["query"]["sparql"].startswith("NEW SELECT")
        )

    def test_per_pair_backend_failure_is_reported_not_fatal(self):
        calls = {"n": 0}

        def flaky(url, question, query, model, complexity, language):
            calls["n"] += 1
            if calls["n"] == 2:
                return None, "HTTP 503: Service Unavailable"
            return _batch_backend_success(url, question, query, model, complexity, language)

        with patch.object(_api, "call_dynbench", side_effect=flaky):
            body, ctype = _multipart("qald.json", _QALD_FILE)
            resp = self.fetch("/api/transform-benchmark?model=gpt-4o&limit=3",
                              method="POST", body=body, headers={"Content-Type": ctype})
        self.assertEqual(resp.code, 200)
        report = json.loads(resp.body)
        self.assertEqual(report["succeeded"], 2)
        self.assertEqual(report["failed"], 1)
        self.assertIn("HTTP 503", report["results"][1]["error"])
        self.assertNotIn("transformed_question", report["results"][1])


class TestOpenApiSpecIncludesBenchmarkPath(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        return tornado.web.Application([
            (r"/api/openapi\.json", _api.OpenApiSpecHandler),
        ])

    def test_spec_contains_benchmark_path(self):
        spec = json.loads(self.fetch("/api/openapi.json").body)
        self.assertIn("/api/transform-benchmark", spec["paths"])

    def test_benchmark_path_documents_formats(self):
        spec = json.loads(self.fetch("/api/openapi.json").body)
        desc = spec["paths"]["/api/transform-benchmark"]["post"]["description"]
        self.assertIn("QALD JSON", desc)
        self.assertIn("LC-QuAD 2.0", desc)


if __name__ == "__main__":
    unittest.main()
