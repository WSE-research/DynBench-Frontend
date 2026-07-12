"""
api.py — exposes call_dynbench as a REST endpoint on Streamlit's Tornado server.

Endpoints
---------
POST /api/transform            — transform a question-query pair (JSON API)
POST /api/transform-benchmark  — transform a complete benchmark file (batch API)
GET  /api/transform            — interactive Swagger UI documentation
GET  /api/openapi.json         — machine-readable OpenAPI 3.0 specification

Request body for POST /api/transform (JSON)
-------------------------------------------
{
    "question":   "<natural-language question>",   # required
    "query":      "<SPARQL query>",                # required
    "complexity": "easy|normal|hard|random",       # optional, default "normal"
    "language":   "<ISO 639-1 code>",              # optional, default "en"
}

POST /api/transform-benchmark
-----------------------------
Upload a benchmark file either as multipart/form-data (field ``file``) or as
the raw request body (then pass ``?filename=…`` for format detection). The
format is auto-detected (same registry as the web UI, see benchmark_formats).
Parameters (query or form fields): ``model`` (required), ``complexity``,
``language``, ``limit`` (number of pairs from the start of the file,
default 10, 0 = all), ``response`` (``json`` = per-pair report, ``file`` =
the transformed benchmark in the exact format of the upload).

The model and DynBench backend URL are taken from the server-side environment
variables MODEL and DYNBENCH, identical to server.py.

Successful response (200)
-------------------------
The raw JSON object returned by the DynBench backend (contains at least
`transformed_question` and `transformed_query`).

Error response (400 / 500)
--------------------------
{ "error": "<human-readable description>" }

Requirement
-----------
This module must be imported *before* ``streamlit.web.bootstrap.run()`` so
that the Tornado route is registered in time.  Use run.py as the entry point.
The patch chains on top of any previously registered patch (e.g. healthcheck).
"""
import asyncio
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor

from decouple import config
import tornado.web
from tornado.routing import PathMatches, Rule
from tornado.web import RequestHandler

import streamlit.web.server.server as _st_server
from benchmark_formats import FORMATS, BatchResult, try_parse_benchmark
from utils import call_dynbench

logger = logging.getLogger(__name__)

_DYNBENCH_URL: str = config("DYNBENCH")

# Available models are read from the MODELS env var (comma-separated).
# Falls back to the single MODEL var when MODELS is not set.
_DEFAULT_MODEL: str = config("MODEL")
_AVAILABLE_MODELS: list[str] = [
    m.strip()
    for m in config("MODELS", default=_DEFAULT_MODEL).split(",")
    if m.strip()
]

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="api-transform")

# ---------------------------------------------------------------------------
# OpenAPI 3.0 specification
# ---------------------------------------------------------------------------

_SUPPORTED_FORMAT_NAMES = ", ".join(f.name for f in FORMATS)

_OPENAPI_SPEC: dict = {
    "openapi": "3.0.0",
    "info": {
        "title": "DynBench Transform API",
        "version": "1.1.0",
        "description": (
            "Generate new question-query pairs that are semantically compatible "
            "with a reference pair and have a configurable entity difficulty."
        ),
    },
    "paths": {
        "/api/transform-benchmark": {
            "post": {
                "summary": "Transform a complete benchmark file (batch)",
                "description": (
                    "Uploads a benchmark file, auto-detects its format and runs the "
                    "contained question-query pairs iteratively through the DynBench "
                    "backend — the programmatic equivalent of the web UI's benchmark "
                    "file upload mode. Upload either as multipart/form-data (field "
                    "``file``) or as the raw request body together with a "
                    "``filename`` parameter for format detection. "
                    f"Supported formats: {_SUPPORTED_FORMAT_NAMES}. "
                    "Note: every pair is one LLM round-trip, so large ``limit`` "
                    "values lead to long-running requests."
                ),
                "parameters": [
                    {
                        "name": "model",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": (
                            "LLM model identifier to use for generation. "
                            "See GET /api/models for available values. "
                            "May alternatively be sent as a form field."
                        ),
                        "example": "gpt-4o",
                    },
                    {
                        "name": "complexity",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "enum": ["easy", "normal", "hard", "random"],
                            "default": "normal",
                        },
                        "description": "Difficulty of the entities in the generated pairs.",
                    },
                    {
                        "name": "language",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "default": "en"},
                        "description": "ISO 639-1 target language code for the generated questions.",
                    },
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "default": 10, "minimum": 0},
                        "description": (
                            "Number of pairs to process, counted from the beginning "
                            "of the file. 0 processes ALL pairs."
                        ),
                    },
                    {
                        "name": "response",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "enum": ["json", "file"],
                            "default": "json",
                        },
                        "description": (
                            "'json' returns a per-pair JSON report; 'file' returns "
                            "the transformed benchmark in the exact same format as "
                            "the uploaded file."
                        ),
                    },
                    {
                        "name": "filename",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                        "description": (
                            "Original file name (used for format detection). Only "
                            "needed when the file is sent as the raw request body "
                            "instead of multipart/form-data."
                        ),
                        "example": "qald-9-test.json",
                    },
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "required": ["file"],
                                "properties": {
                                    "file": {
                                        "type": "string",
                                        "format": "binary",
                                        "description": "The benchmark file.",
                                    },
                                },
                            }
                        },
                        "application/octet-stream": {
                            "schema": {
                                "type": "string",
                                "format": "binary",
                                "description": (
                                    "Raw benchmark file content (pass ?filename=… "
                                    "for format detection)."
                                ),
                            }
                        },
                    },
                },
                "responses": {
                    "200": {
                        "description": (
                            "Batch processed. JSON report (response=json) or the "
                            "transformed benchmark file (response=file)."
                        ),
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "format": {
                                            "type": "string",
                                            "description": "Detected benchmark format.",
                                        },
                                        "total_pairs": {
                                            "type": "integer",
                                            "description": "Pairs found in the file.",
                                        },
                                        "processed": {"type": "integer"},
                                        "succeeded": {"type": "integer"},
                                        "failed": {"type": "integer"},
                                        "results": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "id": {"type": "string"},
                                                    "language": {"type": "string"},
                                                    "question": {"type": "string"},
                                                    "query": {"type": "string"},
                                                    "transformed_question": {"type": "string"},
                                                    "transformed_query": {"type": "string"},
                                                    "selected_replace": {"type": "object"},
                                                    "error": {"type": "string"},
                                                },
                                            },
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "400": {
                        "description": (
                            "Missing file/model, unsupported or unrecognized "
                            "benchmark format, or invalid parameters."
                        ),
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"error": {"type": "string"}},
                                }
                            }
                        },
                    },
                },
            }
        },
        "/api/transform": {
            "post": {
                "summary": "Transform a question-query pair",
                "description": (
                    "Calls the DynBench backend to produce a new natural-language "
                    "question and SPARQL query that are compatible with the supplied "
                    "reference pair. The target language and difficulty of the "
                    "entities in the generated pair can be controlled via optional "
                    "request fields."
                ),
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["question", "query", "model"],
                                "properties": {
                                    "question": {
                                        "type": "string",
                                        "description": "Reference natural-language question.",
                                        "example": "What is the highest mountain in Germany?",
                                    },
                                    "query": {
                                        "type": "string",
                                        "description": "Reference SPARQL query (Wikidata).",
                                        "example": (
                                            "SELECT ?uri WHERE { "
                                            "?uri wdt:P31 wd:Q8502 ; "
                                            "wdt:P17 wd:Q183 . } "
                                            "ORDER BY DESC(?elevation) LIMIT 1"
                                        ),
                                    },
                                    "model": {
                                        "type": "string",
                                        "description": (
                                            "LLM model identifier to use for generation. "
                                            "See GET /api/models for available values."
                                        ),
                                        "example": "gpt-4o",
                                    },
                                    "complexity": {
                                        "type": "string",
                                        "enum": ["easy", "normal", "hard", "random"],
                                        "default": "normal",
                                        "description": (
                                            "Difficulty of the entities in the generated pair, "
                                            "measured by Wikidata PageRank. "
                                            "'easy' = highest PageRank, "
                                            "'hard' = lowest PageRank, "
                                            "'random' = any compatible entity."
                                        ),
                                    },
                                    "language": {
                                        "type": "string",
                                        "default": "en",
                                        "description": "ISO 639-1 target language code for the generated question.",
                                        "example": "de",
                                    },
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Successfully generated question-query pair.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "transformed_question": {
                                            "type": "string",
                                            "description": "Generated natural-language question.",
                                        },
                                        "transformed_query": {
                                            "type": "string",
                                            "description": "Generated SPARQL query.",
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "400": {
                        "description": "Invalid or missing request fields.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "error": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                    "500": {
                        "description": "Backend error or connection failure.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "error": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                },
            }
        },
        "/api/models": {
            "get": {
                "summary": "List available models",
                "description": (
                    "Returns the list of LLM model identifiers configured for this "
                    "server via the MODELS (or MODEL) environment variable. "
                    "Use one of these values as the ``model`` field in POST /api/transform."
                ),
                "responses": {
                    "200": {
                        "description": "Array of model identifiers.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "example": ["gpt-4o", "gpt-3.5-turbo"],
                                }
                            }
                        },
                    },
                    "502": {
                        "description": "Could not reach the DynBench backend.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"error": {"type": "string"}},
                                }
                            }
                        },
                    },
                },
            }
        },
    },
}

# ---------------------------------------------------------------------------
# Swagger UI HTML (served on GET /api/transform)
# ---------------------------------------------------------------------------

_SWAGGER_UI_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <title>DynBench Transform API</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
  <script>
    window.onload = function() {
      SwaggerUIBundle({
        url: "/api/openapi.json",
        dom_id: "#swagger-ui",
        presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
        layout: "StandaloneLayout",
        deepLinking: true,
      });
    };
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

class ApiRootHandler(RequestHandler):
    """Redirect GET /api to the Swagger UI at /api/transform."""

    def check_xsrf_cookie(self) -> None:  # REST endpoint — no XSRF token expected
        pass

    async def get(self) -> None:
        self.redirect("/api/transform", permanent=False)


class OpenApiSpecHandler(RequestHandler):
    """Serve the OpenAPI 3.0 JSON specification at GET /api/openapi.json."""

    def check_xsrf_cookie(self) -> None:  # REST endpoint — no XSRF token expected
        pass

    async def get(self) -> None:
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(_OPENAPI_SPEC, indent=2))


class ModelsHandler(RequestHandler):
    """Return the list of available model identifiers (GET /api/models).

    The list is sourced from the MODELS environment variable (comma-separated).
    Falls back to the MODEL variable when MODELS is not set.  No backend call
    is made; the response is always 200.
    """

    def check_xsrf_cookie(self) -> None:  # REST endpoint — no XSRF token expected
        pass

    async def get(self) -> None:
        self.set_header("Content-Type", "application/json")
        self.set_status(200)
        self.write(json.dumps(_AVAILABLE_MODELS))


class TransformHandler(RequestHandler):
    """Handle GET /api/transform (Swagger UI) and POST /api/transform (JSON API)."""

    def check_xsrf_cookie(self) -> None:  # REST endpoint — no XSRF token expected
        pass

    async def get(self) -> None:
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.write(_SWAGGER_UI_HTML)

    async def post(self) -> None:
        # --- Parse request body ---
        # NOTE: error responses use dict writes — Tornado JSON-encodes and sets
        # the application/json content type itself — and never include
        # exception-derived text (py/reflective-xss, py/stack-trace-exposure).
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.info("API /api/transform: request body is not valid JSON: %s", exc)
            self.set_status(400)
            self.write({"error": "Invalid JSON in the request body."})
            return

        question = body.get("question", "").strip()
        query = body.get("query", "").strip()
        model = body.get("model", "").strip()

        missing = [f for f, v in [("question", question), ("query", query), ("model", model)] if not v]
        if missing:
            self.set_status(400)
            self.write({"error": f"Missing required field(s): {', '.join(missing)}"})
            return

        complexity = body.get("complexity", "normal")
        language = body.get("language", "en")

        logger.info(
            "API /api/transform: question=%r model=%r complexity=%r language=%r",
            question[:80], model, complexity, language,
        )

        # --- Call backend in a thread so we don't block Tornado's event loop ---
        loop = asyncio.get_event_loop()
        result, error = await loop.run_in_executor(
            _executor,
            lambda: call_dynbench(_DYNBENCH_URL, question, query, model, complexity, language),
        )

        if result is not None:
            self.set_status(200)
            self.write(result)
        else:
            self.set_status(500)
            self.write({"error": error})


_EXPORT_CONTENT_TYPES = {
    ".json": "application/json",
    ".xml": "application/xml",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".rq": "application/sparql-query",
    ".sparql": "application/sparql-query",
    ".ttl": "text/turtle",
    ".turtle": "text/turtle",
}


def _process_benchmark_records(records, model, complexity, language):
    """Sequentially transform *records* (runs inside the executor thread)."""
    results = []
    for i, record in enumerate(records):
        logger.info(
            "API batch: pair %d/%d (id %r)", i + 1, len(records), record.id
        )
        response, error = call_dynbench(
            _DYNBENCH_URL, record.question, record.query, model, complexity, language
        )
        if response:
            results.append(
                BatchResult(
                    record=record,
                    new_question=response.get("transformed_question"),
                    new_query=response.get("transformed_query"),
                    response=response,
                )
            )
        else:
            results.append(BatchResult(record=record, error=error))
    return results


class TransformBenchmarkHandler(RequestHandler):
    """POST /api/transform-benchmark — batch-transform an uploaded benchmark file.

    GET serves the Swagger UI (the spec documents all endpoints).
    """

    def check_xsrf_cookie(self) -> None:  # REST endpoint — no XSRF token expected
        pass

    async def get(self) -> None:
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.write(_SWAGGER_UI_HTML)

    def _fail(self, status: int, message: str) -> None:
        self.set_status(status)
        # dict write: Tornado JSON-encodes and sets the application/json
        # content type itself (safe against response-splitting/XSS)
        self.write({"error": message})

    def _uploaded_file(self):
        """Return (filename, content, error) from multipart or the raw body.

        Exactly one of content/error is set; error is always a static message.
        """
        files = self.request.files.get("file")
        if files:
            upload = files[0]
            return upload.filename or "benchmark.json", upload.body, None
        if self.request.body:
            filename = self.get_argument("filename", "")
            if not filename:
                return None, None, (
                    "When the file is sent as the raw request body, the "
                    "'filename' parameter is required for format detection "
                    "(alternatively upload as multipart/form-data field 'file')."
                )
            return filename, self.request.body, None
        return None, None, (
            "No benchmark file supplied. Upload it as multipart/form-data "
            "field 'file' or as the raw request body with ?filename=…"
        )

    async def post(self) -> None:
        filename, content, upload_error = self._uploaded_file()
        if upload_error is not None:
            self._fail(400, upload_error)
            return

        model = self.get_argument("model", "").strip()
        if not model:
            self._fail(400, "Missing required parameter: model")
            return
        complexity = self.get_argument("complexity", "normal")
        language = self.get_argument("language", "en")
        response_mode = self.get_argument("response", "json")
        if response_mode not in ("json", "file"):
            self._fail(400, "Parameter 'response' must be 'json' or 'file'.")
            return
        try:
            limit = int(self.get_argument("limit", "10"))
            if limit < 0:
                raise ValueError
        except ValueError:
            self._fail(400, "Parameter 'limit' must be a non-negative integer (0 = all pairs).")
            return

        fmt, records, parse_error = try_parse_benchmark(filename, content)
        if parse_error is not None:
            self._fail(400, parse_error)
            return

        todo = records if limit == 0 else records[:limit]
        logger.info(
            "API /api/transform-benchmark: file=%r format=%r pairs=%d "
            "processing=%d model=%r complexity=%r language=%r response=%r",
            filename, fmt.name, len(records), len(todo), model, complexity,
            language, response_mode,
        )

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            _executor,
            lambda: _process_benchmark_records(todo, model, complexity, language),
        )

        if response_mode == "file":
            stem, ext = os.path.splitext(os.path.basename(filename))
            # restrict the reflected filename to a safe charset so it cannot
            # break out of the quoted Content-Disposition value
            stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem) or "benchmark"
            ext = ext if re.fullmatch(r"\.[A-Za-z0-9]+", ext or "") else ".json"
            self.set_header(
                "Content-Type",
                _EXPORT_CONTENT_TYPES.get(ext.lower(), "text/plain") + "; charset=utf-8",
            )
            self.set_header("X-Content-Type-Options", "nosniff")
            self.set_header(
                "Content-Disposition",
                f'attachment; filename="{stem}-transformed{ext}"',
            )
            self.write(fmt.export(results))
            return

        report = {
            "format": fmt.name,
            "total_pairs": len(records),
            "processed": len(results),
            "succeeded": sum(1 for r in results if r.error is None),
            "failed": sum(1 for r in results if r.error is not None),
            "results": [
                {
                    "id": r.record.id,
                    "language": r.record.language,
                    "question": r.record.question,
                    "query": r.record.query,
                    **(
                        {
                            "transformed_question": r.new_question,
                            "transformed_query": r.new_query,
                            "selected_replace": (r.response or {}).get("selected_replace"),
                        }
                        if r.error is None
                        else {"error": r.error}
                    ),
                }
                for r in results
            ],
        }
        # dict write: Tornado JSON-encodes and sets application/json itself
        self.write(report)


# ---------------------------------------------------------------------------
# Patch start_listening to register routes
# ---------------------------------------------------------------------------

# Chain this patch on top of whatever is currently registered as start_listening
# (healthcheck.py installs its own patch first; we wrap that).
_prev_start_listening = _st_server.start_listening


def _patched_start_listening(app: tornado.web.Application) -> None:
    app.wildcard_router.rules.insert(0, Rule(PathMatches(r"/api/openapi\.json"), OpenApiSpecHandler))
    app.wildcard_router.rules.insert(0, Rule(PathMatches(r"/api/models"), ModelsHandler))
    app.wildcard_router.rules.insert(0, Rule(PathMatches(r"/api/transform-benchmark"), TransformBenchmarkHandler))
    app.wildcard_router.rules.insert(0, Rule(PathMatches(r"/api/transform"), TransformHandler))
    app.wildcard_router.rules.insert(0, Rule(PathMatches(r"/api"), ApiRootHandler))
    logger.info(
        "Registered /api, /api/transform, /api/transform-benchmark, /api/models, "
        "/api/openapi.json on Streamlit's Tornado server"
    )
    _prev_start_listening(app)


_st_server.start_listening = _patched_start_listening
