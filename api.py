"""
api.py — exposes call_dynbench as a REST endpoint on Streamlit's Tornado server.

Endpoints
---------
POST /api/transform      — transform a question-query pair (JSON API)
GET  /api/transform      — interactive Swagger UI documentation
GET  /api/openapi.json   — machine-readable OpenAPI 3.0 specification

Request body for POST (JSON)
-----------------------------
{
    "question":   "<natural-language question>",   # required
    "query":      "<SPARQL query>",                # required
    "complexity": "easy|normal|hard|random",       # optional, default "normal"
    "language":   "<ISO 639-1 code>",              # optional, default "en"
}

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
from concurrent.futures import ThreadPoolExecutor

from decouple import config
from tornado.routing import PathMatches, Rule
from tornado.web import RequestHandler

import streamlit.web.server.server as _st_server
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

_OPENAPI_SPEC: dict = {
    "openapi": "3.0.0",
    "info": {
        "title": "DynBench Transform API",
        "version": "1.0.0",
        "description": (
            "Generate new question-query pairs that are semantically compatible "
            "with a reference pair and have a configurable entity difficulty."
        ),
    },
    "paths": {
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
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, ValueError) as exc:
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"error": f"Invalid JSON: {exc}"}))
            return

        question = body.get("question", "").strip()
        query = body.get("query", "").strip()
        model = body.get("model", "").strip()

        missing = [f for f, v in [("question", question), ("query", query), ("model", model)] if not v]
        if missing:
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"error": f"Missing required field(s): {', '.join(missing)}"}))
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

        self.set_header("Content-Type", "application/json")
        if result is not None:
            self.set_status(200)
            self.write(json.dumps(result))
        else:
            self.set_status(500)
            self.write(json.dumps({"error": error}))


# ---------------------------------------------------------------------------
# Patch start_listening to register routes
# ---------------------------------------------------------------------------

# Chain this patch on top of whatever is currently registered as start_listening
# (healthcheck.py installs its own patch first; we wrap that).
_prev_start_listening = _st_server.start_listening


def _patched_start_listening(app: "tornado.web.Application") -> None:  # type: ignore[name-defined]
    app.wildcard_router.rules.insert(0, Rule(PathMatches(r"/api/openapi\.json"), OpenApiSpecHandler))
    app.wildcard_router.rules.insert(0, Rule(PathMatches(r"/api/models"), ModelsHandler))
    app.wildcard_router.rules.insert(0, Rule(PathMatches(r"/api/transform"), TransformHandler))
    app.wildcard_router.rules.insert(0, Rule(PathMatches(r"/api"), ApiRootHandler))
    logger.info("Registered /api, /api/transform, /api/models, /api/openapi.json on Streamlit's Tornado server")
    _prev_start_listening(app)


_st_server.start_listening = _patched_start_listening
