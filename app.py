import os
import logging
import json
import random


from decouple import config

import colorlog
import streamlit as st
from streamlit.components.v1 import html

from PIL import Image
import base64

import healthcheck
from sample_selector import (
    select_sample,
    build_samples_by_id,
    build_samples_by_language,
)
from utils import (
    call_dynbench,
    output_row,
    format_sparql,
    submit_feedback,
    get_models
)
from batch_ui import render_batch_mode
from settings import (
    PAGE_IMAGE,
    PAGE_TITLE,
    PAGE_ICON,
    LANGUAGES,
    LANGUAGE_CODES,
    GITHUB_REPO,
    DEFAULT_QUERY_INPUT_HEIGHT,
)

handler = colorlog.StreamHandler()
handler.setFormatter(
    colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s %(levelname)-8s%(reset)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    )
)
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger(__name__)


st.set_page_config(
    layout="wide",
    page_title=PAGE_TITLE,
    page_icon=Image.open(PAGE_ICON)
)


# class States(Enum):
#     STARTUP = 1
#     NO_RESULT = 2
#     SHOW_RESULT = 3
#     SHOW_ERROR = 4


# # state management
# if 'state' not in st.session_state:
#     st.session_state.state = States.STARTUP
#     # call init sequence initialize(args)

# match st.session_state.state:
#     case States.STARTUP:
#         pass # raise error
#     case States.NO_RESULT:
#         pass # show input fields
#     case States.NO_RESULT:
#         pass # show input and output
#     case States.NO_RESULT:
#         pass # show error


# One-time running code
if 'dyn_base_url' not in st.session_state:
    st.session_state.dyn_base_url  = config('DYNBENCH')
    st.session_state.transform_url = config('DYNBENCH')+'/transform'
    st.session_state.feedback_url  = config('DYNBENCH')+'/feedback'

    st.session_state.models_list = get_models()

    logger.info(f'DynBench URL: {st.session_state.dyn_base_url}')
    healthcheck.start_background_check(st.session_state.dyn_base_url)

    with open('benchmarks/DynQALD.json', 'r') as f:
        st.session_state.samples = json.load(f)

    st.session_state.samples_by_id = build_samples_by_id(st.session_state.samples)
    st.session_state.samples_by_language = build_samples_by_language(
        st.session_state.samples
    )
    logger.info(
        "Loaded %d samples. Available IDs: %s",
        len(st.session_state.samples),
        ", ".join(st.session_state.samples_by_id.keys()),
    )
    logger.info(
        "Available sample languages: %s",
        ", ".join(sorted(st.session_state.samples_by_language.keys())),
    )
    # Sorted list of (display_name, iso_code) for the sidebar checkboxes.
    # Falls back to the raw ISO code when no display-name mapping is available.
    st.session_state.available_sample_languages = sorted(
        [
            (LANGUAGE_CODES.get(code, code), code)
            for code in st.session_state.samples_by_language.keys()
        ],
        key=lambda x: x[0],
    )
    # No pre-selection: inputs start empty until params or button set a record
    st.session_state.random_record = None


with (
    open("css/style_menu_logo.css") as f,
    open("css/style_github_ribbon.css") as g,
    open("css/custom.css") as h,
):
    st.markdown(
        f"<style>{f.read()}{g.read()}{h.read()}</style>", unsafe_allow_html=True
    )

st.markdown(
    """
    <style>
    /* Target the container for the running man animation specifically */
    div[data-testid="stStatusWidget"] svg {
        display: none !important;
    }
    /* Ensure the Stop button remains visible and clickable */
    div[data-testid="stStatusWidget"] button {
        display: block !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# --- Read URL params early so the sidebar can use them for pre-selection ---
_sample_id = st.query_params.get("sample_id")
_sample_language = st.query_params.get("sample_language")


# When sample_language changes (or appears for the first time), tick the
# corresponding checkbox — but only when the user has not manually interacted
# with the checkboxes yet.  Once _lang_filter_manual is True the user's own
# selection takes full precedence over the URL parameter.
if not st.session_state.get("_lang_filter_manual", False):
    if st.session_state.get("_last_sample_language_param") != _sample_language:
        st.session_state["_last_sample_language_param"] = _sample_language
        if _sample_language is not None:
            st.session_state[f"lang_filter_{_sample_language}"] = True


# === Usage modes ==============================================================
# Selected in the sidebar (box below the logo), persisted in a cookie so the
# preferred mode is activated by default on the next visit. On the very first
# visit (no cookie) a centered selector is shown instead.

_MODE_COOKIE = "dynbench_usage_mode"

USAGE_MODES = {
    "single": {"icon": "✍️", "label": "one question+query", "color": "blue", "hex": "#0068C9"},
    "batch": {"icon": "📤", "label": "file upload", "color": "orange", "hex": "#D97C08"},
    "api": {"icon": "🔌", "label": "RESTful API", "color": "green", "hex": "#21A366"},
}

if "usage_mode" not in st.session_state:
    _cookie_mode = st.context.cookies.get(_MODE_COOKIE, "")
    if _cookie_mode in USAGE_MODES:
        st.session_state.usage_mode = _cookie_mode
    elif _sample_id is not None or _sample_language is not None:
        # deep links to sample pairs are single-pair links
        st.session_state.usage_mode = "single"


def _mode_option_label(mode: str) -> str:
    m = USAGE_MODES[mode]
    return f":{m['color']}[{m['icon']} {m['label']}]"


def _usage_mode_radio_changed():
    st.session_state.usage_mode = st.session_state._usage_mode_radio


def render_title(mode=None):
    """Page title; with a tag-like label showing the active usage mode."""
    if mode is None:
        st.title("DynBench: Question-Query Pair Generator")
        return
    m = USAGE_MODES[mode]
    st.markdown(
        "<h1>DynBench: Question-Query Pair Generator "
        f"<span style='background:{m['hex']}1a; color:{m['hex']}; "
        f"border:1.5px solid {m['hex']}; border-radius:1rem; padding:0.1em 0.6em; "
        "font-size:0.45em; font-weight:600; vertical-align:middle; "
        f"white-space:nowrap;'>{m['icon']} {m['label']}</span></h1>",
        unsafe_allow_html=True,
    )


def render_landing():
    """First visit (no stored preference): centered usage-mode selector."""
    render_title(None)
    st.subheader(
        "Generate new question-query pairs for overcoming memorization effects "
        "during benchmarking LLM-based systems."
    )
    st.write("")
    _, _mid, _ = st.columns([1, 1.1, 1])
    with _mid:
        with st.container(border=True):
            st.markdown("### Usage mode")
            st.write("How would you like to use DynBench?")
            for _key in USAGE_MODES:
                if st.button(
                    _mode_option_label(_key),
                    key=f"choose_{_key}",
                    use_container_width=True,
                ):
                    st.session_state.usage_mode = _key
                    st.rerun()
            st.caption("Your choice is remembered for the next visit.")


def render_api_mode():
    """Usage mode 'RESTful API': point to the OpenAPI description of the API."""
    _host = st.context.headers.get("Host", "localhost:8501")
    _proto = st.context.headers.get("X-Forwarded-Proto", "http")
    _base = f"{_proto}://{_host}"
    st.write(
        "Everything DynBench offers in the browser is also available to "
        "programs through a REST API — both usage modes: transforming **one "
        "question+query** pair (`POST /api/transform`) and processing a "
        "complete benchmark **file upload** (`POST /api/transform-benchmark`, "
        "with automatic benchmark-format detection and export in the format "
        "of the uploaded file). The full API — endpoints, parameters, "
        "request/response schemas and the supported benchmark formats — is "
        "described by an OpenAPI 3.0 specification:"
    )
    col_docs, col_spec, _ = st.columns([1, 1, 1])
    with col_docs:
        st.link_button(
            "📖 Interactive API documentation (Swagger UI)",
            f"{_base}/api/transform",
            use_container_width=True,
        )
    with col_spec:
        st.link_button(
            "📄 OpenAPI 3.0 specification (JSON)",
            f"{_base}/api/openapi.json",
            use_container_width=True,
        )
    st.markdown(
        f"""
| Endpoint | Purpose |
|---|---|
| `POST {_base}/api/transform` | transform one question+query pair |
| `POST {_base}/api/transform-benchmark` | transform a complete benchmark file |
| `GET {_base}/api/models` | list the available LLM models |
| `GET {_base}/api/openapi.json` | machine-readable OpenAPI 3.0 specification |
"""
    )
    st.markdown("**Examples**")
    st.code(
        f"""# transform one question+query pair
curl -X POST '{_base}/api/transform' \\
  -H 'Content-Type: application/json' \\
  -d '{{"question": "What is …?", "query": "SELECT …", "model": "gpt-4o"}}'

# transform the first 10 pairs of a benchmark file (any supported format)
curl -X POST '{_base}/api/transform-benchmark?model=gpt-4o&limit=10' \\
  -F 'file=@qald-9-test.json'

# get the whole transformed benchmark back in the exact format of the upload
curl -X POST '{_base}/api/transform-benchmark?model=gpt-4o&limit=0&response=file' \\
  -F 'file=@qald-9-test.json' -o qald-9-test-transformed.json""",
        language="bash",
    )


def page_footer():
    """Menu JS, GitHub ribbon and the usage-mode cookie (all display modes)."""
    with open("js/change_menu.js", "r") as f:
        html(f"<script style='display:none'>{f.read()}</script>")

    html(
        """
        <script>
        github_ribbon = parent.window.document.createElement("div");
        github_ribbon.innerHTML = '<a id="github-fork-ribbon" class="github-fork-ribbon right-bottom" href="%s" target="_blank" data-ribbon="Fork me on GitHub" title="Fork me on GitHub">Fork me on GitHub</a>';
        if (parent.window.document.getElementById("github-fork-ribbon") == null) {
            parent.window.document.body.appendChild(github_ribbon.firstChild);
        }
        </script>
        """
        % (GITHUB_REPO,)
    )

    _mode = st.session_state.get("usage_mode")
    if _mode in USAGE_MODES:
        # persist the preferred usage mode for one year (component iframes are
        # same-origin, so the cookie lands on the app's own origin)
        html(
            "<script>parent.document.cookie = "
            f"'{_MODE_COOKIE}={_mode}; path=/; max-age=31536000; SameSite=Lax';"
            "</script>",
            height=0,
        )


# === Sidebar ===
with st.sidebar:
    with open(PAGE_IMAGE, "rb") as f:
        # Read the optional file VERSION.txt containing version number
        version = ""
        version_long = ""
        if os.path.exists("VERSION.txt"):
            with open("VERSION.txt", "r") as version_file:
                version = version_file.read().strip()
                version_long = ", current version " + version

        image_data = base64.b64encode(f.read()).decode("utf-8")
        st.sidebar.markdown(
            f"""
            <div style="display:table;margin-top:-10%;margin-bottom:15%;margin-left:auto;margin-right:auto;text-align:center">
                <a href="{GITHUB_REPO}" title="go to GitHub repository{version_long}"><img src="data:image/png;base64,{image_data}" class="app_logo"></a>
            </div>
            """,
            unsafe_allow_html=True,
        )

    _usage_mode = st.session_state.get("usage_mode")

    # Usage-mode selector below the logo. Hidden on the very first visit,
    # where the selector is shown in the center of the page instead.
    if _usage_mode is not None:
        with st.container(border=True):
            st.markdown("**Usage mode**")
            st.radio(
                "Usage mode",
                list(USAGE_MODES),
                index=list(USAGE_MODES).index(_usage_mode),
                format_func=_mode_option_label,
                key="_usage_mode_radio",
                on_change=_usage_mode_radio_changed,
                label_visibility="collapsed",
            )
        _usage_mode = st.session_state.get("usage_mode")

    model = None
    difficulty = None
    language = None
    if _usage_mode in ("single", "batch"):
        st.title("Settings")

        model = st.selectbox(
            "Select LLM to generate new question:",
            st.session_state.models_list,
        )

        _DIFFICULTY_ICONS = {"easy": "🟢", "similar": "≈", "hard": "🔴", "random": "🎲"}
        difficulty = st.radio(
            "Select difficulty for the entities in the generated question-query pair:",
            ["easy", "similar", "hard", "random"],
            index=1,
            format_func=lambda d: f"{_DIFFICULTY_ICONS[d]} {d}",
            captions=[
                "Select the compatible entity with highest PageRank",
                "Use similar entity PageRanks in the generated question as in the reference question",
                "Select the compatible entity with lowest PageRank",
                "Select a compatible entity with a difficulty between the highest and lowest PageRank",
            ],
            help='A higher PageRank means a less difficult question-query pair as the entities are more commonly used in the language. The PageRank is calculated based on the Wikidata knowledge graph. Choose "Same as the original" to generate a question-query pair that should have the same difficulty as the original question-query pair. Choose "Any compatible" to generate a question-query pair that is compatible with the original question-query pair and has a difficulty between the highest and lowest PageRank (random).',
        )
        if difficulty == "similar":
            difficulty = "normal"

        language = st.selectbox(
            "Select language for the to-be-generated question:",
            list(LANGUAGES),
        )

    if _usage_mode == "single":
        def _mark_lang_filter_manual():
            st.session_state["_lang_filter_manual"] = True

        st.subheader(
            "Filter sample question-query pairs by language:",
            help="Only selected languages will be considered when clicking 'Random sample'. If none are selected, all languages are used.",
        )
        for _display_name, _iso_code in st.session_state.available_sample_languages:
            # if no sample_language is selected, check all languages
            if _sample_language is None:
                st.checkbox(
                    _display_name,
                    key=f"lang_filter_{_iso_code}",
                    on_change=_mark_lang_filter_manual,
                    value=True,
                )
            else:
                # if a sample_language is selected, check the corresponding language
                if _sample_language == _iso_code:
                    st.checkbox(
                        _display_name,
                        key=f"lang_filter_{_iso_code}",
                        on_change=_mark_lang_filter_manual,
                    )
                else:
                    st.checkbox(
                        _display_name,
                        key=f"lang_filter_{_iso_code}",
                        on_change=_mark_lang_filter_manual,
                        value=False,
                    )

    st.divider()

    _backend_status = healthcheck.get_status()
    if _backend_status["ok"]:
        st.caption("✅ Backend reachable")
    else:
        st.error("🚨 Backend unreachable!")

_effective_sample_language = (
    None if st.session_state.get("_lang_filter_manual", False) else _sample_language
)

if _sample_id is not None or _effective_sample_language is not None:
    # At least one param present: always re-derive the record so the UI
    # stays in sync with the URL even after unrelated reruns.
    _record = select_sample(
        st.session_state.samples,
        st.session_state.samples_by_id,
        st.session_state.samples_by_language,
        sample_id=_sample_id,
        sample_language=_effective_sample_language,
        random_fallback=False,
    )
    st.session_state.random_record = _record
    if _record is not None:
        logger.info(
            "Selected sample id=%r language=%r via params sample_id=%r sample_language=%r",
            _record.get("id"),
            _record.get("language"),
            _sample_id,
            _effective_sample_language,
        )
    else:
        logger.warning(
            "No sample found for sample_id=%r sample_language=%r",
            _sample_id,
            _effective_sample_language,
        )      

# === Mode dispatch ============================================================
_usage_mode = st.session_state.get("usage_mode")

if _usage_mode is None:
    # first visit: selector in the center of the page, sidebar selector hidden
    render_landing()
    page_footer()
    st.stop()

render_title(_usage_mode)

if _usage_mode == "api":
    render_api_mode()
    page_footer()
    st.stop()

if _usage_mode == "batch":
    render_batch_mode(
        st.session_state.transform_url, model, difficulty, LANGUAGES[language]
    )
    page_footer()
    st.stop()

# --- usage mode "one question+query" (fall-through) ---------------------------
st.subheader(
    "Generate new question-query pairs for overcoming memorization effects during benchmarking LLM-based systems."
)
st.write(
    "Generate new question-query pairs that are compatible with the original question-query pair and have a user-selected difficulty (configurable on the sidebar). The difficulty is measured by the PageRank of the entities in the question-query pair. The PageRank is calculated based on the Wikidata knowledge graph."
)
col_title, col_random = st.columns([4, 1])
with col_title:
    st.write(
        "Insert your reference question-query pair or click 'Random sample' to use a randomly selected question-query pair."
    )

with col_random:
    if st.button("Random sample"):
        st.query_params.pop("sample_id", None)
        st.query_params.pop("new_question", None)
        
        # if "sample_id" in st.query_params:
        #     del st.query_params["sample_id"]
        # Collect languages ticked in the sidebar filter checkboxes.
        _checked_langs = {
            code
            for _, code in st.session_state.available_sample_languages
            if st.session_state.get(f"lang_filter_{code}", False)
        }
        if _checked_langs:
            _pool = [
                s for s in st.session_state.samples if s["language"] in _checked_langs
            ]
            st.session_state.random_record = random.choice(_pool) if _pool else None
            logger.info(
                "Random sample selected from manually filtered languages: %s (pool size: %d)",
                ", ".join(sorted(_checked_langs)),
                len(_pool),
            )
        else:
            st.session_state.random_record = select_sample(
                st.session_state.samples,
                st.session_state.samples_by_id,
                st.session_state.samples_by_language,
                sample_id=None,
                sample_language=None,
                random_fallback=True,
            )
            logger.info("Random sample selected from all languages (no filter active)")
        st.rerun()

col1, col2 = st.columns(2)

_record = st.session_state.get("random_record")

_current_record_key = (_record["id"], _record.get("language")) if _record else None
if st.session_state.get("_loaded_record_key") != _current_record_key:
    st.session_state["_loaded_record_key"] = _current_record_key
    st.session_state.question_input = _record["question"] if _record else ""
    st.session_state.query_input = (
        format_sparql(_record["query"]) if _record else ""
    )

lines = len(st.session_state.get("query_input", "").split("\n")) + 2
textarea_height = (
    "stretch"
    if not st.session_state.get("question_input", "")
    else DEFAULT_QUERY_INPUT_HEIGHT * lines
)

with col1:
    st.text_area(
        "Reference question",
        key="question_input",
        placeholder="Enter your reference question",
        help="The question you want to use as a reference for the generation of a new question-query pair.",
        height=textarea_height,
    )

with col2:
    st.text_area(
        "Reference SPARQL query",
        key="query_input",
        placeholder="Enter your reference SPARQL query",
        help="The SPARQL query you want to use as a reference for the generation of a new question-query pair. The SPARQL query should be a valid SPARQL query that can be executed against the Wikidata knowledge graph and is reflecting the meaning of the reference question.",
        height=textarea_height,
    )

_, _btn_col, _ = st.columns([1, 2, 1])
with _btn_col:
    submit = st.button(
        f"Generate using {model.split('/')[-1] if '/' in model else model} 🚀",
        use_container_width=True,
        key="form_submit_button",
    )


if submit:
    question = st.session_state.question_input
    query = st.session_state.query_input

    # logger.info(f'Run new generation for question {question}')
    # logger.info(f'Query: {query}')

    if not question.strip() or not query.strip():
        missing = []
        if not question.strip():
            missing.append("reference question")
        if not query.strip():
            missing.append("reference SPARQL query")
        st.warning(f"Please provide a {' and a '.join(missing)} before generating.")
        st.stop()

    logger.info(f'Run new generation for question "{question}" and query "{query}"')

    with st.spinner(
        "Generating question-query pair using " + model + "...", show_time=True
    ):
        r, error = call_dynbench(
            st.session_state.transform_url,
            question,
            query,
            model,
            difficulty,
            LANGUAGES[language],
        )

        print(r)

    if r:
        st.session_state["new_question"] = r["transformed_question"]
        st.session_state["new_query"] = r["transformed_query"]
        st.session_state["response_data"] = r
        
        # dump the response data formatted as JSON to the log
        logger.info("response data: %r", json.dumps(r, indent=2, ensure_ascii=False))
        
        # log all key of the response data to the log
        logger.info("response data keys: %r", list(r.keys()))
        
        st.session_state["selected_replace"] = r["extra"].get("selected_replace", {})
        logger.info("selected_replace stored: %s", json.dumps(st.session_state["selected_replace"], indent=2, ensure_ascii=False))
        detected_code = (
            r.get('extra', {}).get('Original language')
            or r.get('extra', {}).get("detected_language")
            or r.get('extra', {}).get("original_language")
            or r.get("source_language", None)
            or r.get("lang", None)
            or LANGUAGES[language]
        )
        detected_name = LANGUAGE_CODES.get(detected_code, detected_code)
        st.session_state["detected_language"] = f"{detected_name} ({detected_code})"
    else:
        st.session_state.pop("new_question", None)
        st.session_state.pop("new_query", None)
        st.session_state.pop("selected_replace", None)
        logger.warning(
            "No question-query generated for question=%r, query=%r — reason: %s",
            question,
            query,
            error,
        )
        st.subheader(":red[Error]")
        st.text("Sorry, no question-query pair was generated.")
        st.error(error)

if 'new_question' in st.session_state:
    question = st.session_state['question_input']
    query = st.session_state['query_input']
    new_question = st.session_state['new_question']
    new_query = st.session_state['new_query']

    detected_language = st.session_state.get("detected_language", "")
    st.subheader("Generated question-query pair")
    output_row(
        "Recognized language of original question",
        detected_language,
        "detected_language",
        question,
        query,
        new_question,
        new_query,
    )
    _sr = st.session_state.get("selected_replace") or {}
    if _sr:
        def _entity_text(label, entity, pagerank):
            """Build an HTML string with a Wikidata hyperlink for *entity*.

            The value is rendered inside a <p> tag with unsafe_allow_html=True,
            so we produce <a> elements rather than Markdown link syntax.
            entity is typically "wd:Q1234"; the QID after the colon is used to
            build the Wikidata URL.
            """
            qid = entity.split(":")[-1] if entity else ""
            wd_url = f"https://www.wikidata.org/wiki/{qid}" if qid else ""
            a = f'<a href="{wd_url}" target="_blank" rel="noopener noreferrer">'
            if label and wd_url:
                linked = f'{a}{label} ({entity}</a>)'
            elif label:
                linked = label + (f" ({entity})" if entity else "")
            elif wd_url:
                linked = f'{a}{entity}</a>'
            else:
                linked = entity or ""
            if pagerank != "":
                linked += f" — PageRank: {pagerank}"
            return linked

        output_row(
            "Recognized entity in the reference question",
            _entity_text(_sr.get("old_label", ""), _sr.get("old_entity", ""), _sr.get("old_pagerank", "")),
            "old_entity",
            question,
            query,
            new_question,
            new_query,
        )
        output_row(
            "Entity used in the generated question",
            _entity_text(_sr.get("new_label", ""), _sr.get("new_entity", ""), _sr.get("new_pagerank", "")),
            "new_entity",
            question,
            query,
            new_question,
            new_query,
        )
    output_row(
        "Generated question based on the reference question (and query)",
        new_question,
        "new_question",
        question,
        query,
        new_question,
        new_query,
    )
    try:
        _formatted_new_query = format_sparql(new_query)
        logger.info(f"Formatted new query: {_formatted_new_query}")
    except Exception:
        logger.error(f"Error formatting new query: {new_query}")
        _formatted_new_query = new_query
    output_row(
        "Generated SPARQL query based on the reference query (and question)",
        _formatted_new_query,
        "new_query",
        question,
        query,
        new_question,
        new_query,
        format="sparql",
    )

    _, _btn_col, _ = st.columns([1, 2, 1])
    with _btn_col:
        if st.button(
            ":green[👍 Everything is OK]",
            use_container_width=True,
            key="bt_everything_ok",
        ):
            submit_feedback(
                question, 
                query, 
                new_question, 
                new_query, 
                'everything', 
                f'detected_language: {detected_language}', 
                1
            )

    st.divider()

st.write("")

with st.expander("API request (curl)"):
    _curl_payload = {
        "question": st.session_state.get("question_input", ""),
        "query": st.session_state.get("query_input", ""),
        "model": model,
        "complexity": difficulty,
        "language": LANGUAGES[language],
    }
    _curl_json = json.dumps(_curl_payload, indent=2, ensure_ascii=False)
    _host = st.context.headers.get("Host", "localhost:8501")
    _proto = st.context.headers.get("X-Forwarded-Proto", "http")
    _api_url = f"{_proto}://{_host}/api/transform"
    st.code(
        f"curl -X POST '{_api_url}' \\\n"
        f"  -H 'Content-Type: application/json' \\\n"
        f"  -d '{_curl_json}'",
        language="bash",
    )    

if "new_question" in st.session_state:
    with st.expander("Full response data"):
        _FIELD_LABELS = {
            "original_question":  "Reference question",
            "original_query":     "Reference SPARQL query",
            "transformed_question": "Generated question",
            "transformed_query":  "Generated SPARQL query",
            "old_pagerank":       "Pagerank of entity in reference question",
            "new_pagerank":       "Pagerank of entity in generated question",
            "extra":              "Raw data",
        }
        _response_data = st.session_state.get("response_data", {})
        for _key, _raw_value in _response_data.items():
            _label = _FIELD_LABELS.get(_key, _key)
            st.markdown(f"**{_label}**")
            if _key in ("original_query", "transformed_query"):
                try:
                    _display_value = format_sparql(str(_raw_value))
                except Exception:
                    _display_value = str(_raw_value)
                st.code(_display_value, language="sparql")
            elif _key == "extra":
                try:
                    _pretty = json.dumps(
                        _raw_value if not isinstance(_raw_value, str) else json.loads(_raw_value),
                        indent=2,
                        ensure_ascii=False,
                    )
                except Exception:
                    _pretty = str(_raw_value)
                st.code(_pretty, language="json")
            else:
                st.text(str(_raw_value))


page_footer()
