import os
import logging
import requests
import json
import random

import sparqlib
import healthcheck
from sample_selector import (
    select_sample,
    build_samples_by_id,
    build_samples_by_language,
)
from decouple import config
# from decouple import Config, RepositoryEnv

import colorlog
import streamlit as st
from streamlit.components.v1 import html

from PIL import Image
import base64

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


DEFAULT_QUERY_INPUT_HEIGHT = 24  # pixels
MODEL = config("MODEL")
GITHUB_REPO = config(
    "GITHUB_REPO", "https://github.com/WSE-research/DynBench-Frontend.git"
)

PAGE_TITLE = "DynBench: robust benchmark records generator"
# PAGE_IMAGE = 'images/dynbench.png'
PAGE_IMAGE = "images/dynbench-logo-alpha.png"

LANGUAGES = {  # display name → ISO code
    "English": "en",
    "German": "de",
    "French": "fr",
    "Russian": "ru",
    "Ukrainian": "uk",
    "Italian": "it",
    "Spanish": "es",
    "Polish": "pl",
    "Romanian": "ro",
    "Dutch": "nl",
    "Turkish": "tr",
    "Bavarian": "bar",
    "Portuguese": "pt",
    "Hungarian": "hu",
    "Greek": "el",
    "Czech": "cs",
    "Swedish": "sv",
    "Catalan": "ca",
    "Serbian": "sr",
    "Bulgarian": "bg",
}
LANGUAGE_CODES = {
    code: name for name, code in LANGUAGES.items()
}  # ISO code → display name


def call_dynbench(url, question, query, model, complexity="normal", language="en"):
    """Return (result_dict, error_str). On success error_str is None; on failure result_dict is None."""
    headers = {}
    data = {
        "question": question,
        "query": query,
        "model": model,
        "lang": language,
        "complexity": complexity,
        "checks": ["sentence"],
    }

    try:
        r = requests.post(url, headers=headers, json=data, timeout=30)
    except requests.exceptions.ConnectionError as e:
        return None, f"Connection error: {e}"
    except requests.exceptions.Timeout:
        return None, "Request timed out after 30 s"
    except requests.exceptions.RequestException as e:
        return None, f"Request failed: {e}"

    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text.strip()}"

    try:
        body = r.json()
    except Exception as e:
        return None, f"Could not parse response as JSON: {e} — raw: {r.text[:200]}"

    missing = [
        k for k in ("transformed_question", "transformed_query") if not body.get(k)
    ]
    if missing:
        return None, f"Response missing field(s): {', '.join(missing)} — body: {body}"

    return body, None


# config = Config(RepositoryEnv("config.env"))

if "dynbench" not in st.session_state:
    st.session_state["dynbench"] = config("DYNBENCH")
    logger.info("DynBench URL: %s", st.session_state.dynbench)
    healthcheck.start_background_check(st.session_state.dynbench)

    with open("benchmarks/DynQALD.json", "r") as f:
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


st.set_page_config(
    layout="wide",
    page_title=PAGE_TITLE,
    # page_icon=Image.open(PAGE_ICON)
)

with open("css/style_menu_logo.css") as f, open("css/style_github_ribbon.css") as g:
    st.markdown(f"<style>{f.read()}{g.read()}</style>", unsafe_allow_html=True)

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

# --- Sidebar ---
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

    st.title("Settings")

    difficulty = st.radio(
        "Select difficulty for the entities in the generated question-query pair:",
        ["easy", "normal", "hard", "random"],
        index=1,
        captions=[
            "Select the compatible entity with highest PageRank",
            "Similar entity PageRank as the original entities",
            "Select the compatible entity with lowest PageRank",
            "Select a compatible entity with a difficulty between the highest and lowest PageRank",
        ],
        help='A higher PageRank means a less difficult question-query pair as the entities are more commonly used in the language. The PageRank is calculated based on the Wikidata knowledge graph. Choose "Same as the original" to generate a question-query pair that should have the same difficulty as the original question-query pair. Choose "Any compatible" to generate a question-query pair that is compatible with the original question-query pair and has a difficulty between the highest and lowest PageRank (random).',
    )

    language = st.selectbox(
        "Select language for the to-be-generated question:",
        list(LANGUAGES),
    )

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
        st.error(f"Backend unreachable: {_backend_status['message']}", icon="🚨")

# --- Resolve the active record from query parameters ---
# (_sample_id and _sample_language were read before the sidebar block above.)
#
# When the user has manually interacted with the language filter checkboxes
# their selection takes full precedence: the sample_language URL param must
# no longer influence which record is loaded, so we treat it as absent.
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
# Neither param present (or manual filter active): leave random_record as-is.

# --- Main panel ---
st.title("DynBench: Question-Query Pair Generator")
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
        if "sample_id" in st.query_params:
            del st.query_params["sample_id"]
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

# Only overwrite the textarea contents when the loaded record changes.
# Using (id, language) as the key means user edits are preserved across
# all other reruns (widget interactions, sidebar changes, etc.).
_current_record_key = (
    (_record["id"], _record.get("language")) if _record else None
)
if st.session_state.get("_loaded_record_key") != _current_record_key:
    st.session_state["_loaded_record_key"] = _current_record_key
    st.session_state.question_input = _record["question"] if _record else ""
    st.session_state.query_input = (
        sparqlib.format_string(_record["query"]) if _record else ""
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
    submit = st.button(f":blue[Generate using {MODEL} 🚀]", use_container_width=True)

# --- Output fields ---
# st.subheader("Output")

# output_1 = st.text_area('New question', value='', height=80, disabled=True)
# output_2 = st.text_area('New query', value='', height=80, disabled=True)


def submit_feedback(question, query, new_question, new_query, object, feedback):
    pass


if submit:
    question = st.session_state.question_input
    query = st.session_state.query_input

    if not question.strip() or not query.strip():
        missing = []
        if not question.strip():
            missing.append("reference question")
        if not query.strip():
            missing.append("reference SPARQL query")
        st.warning(f"Please provide a {' and a '.join(missing)} before generating.")
        st.stop()

    logger.info(f'Run new generation for question "{question}" and query "{query}"')
    # logger.info("Question: %s", question)
    # logger.info("Query: %s", query)

    # call_dynbench(url, question, query, model, complexity="normal", language="en")

    r, error = call_dynbench(
        st.session_state.dynbench,
        question,
        query,
        MODEL,
        difficulty,
        LANGUAGES[language],
    )

    if r:
        st.session_state["new_question"] = r["transformed_question"]
        st.session_state["new_query"] = r["transformed_query"]
        detected_code = (
            r.get("detected_language")
            or r.get("original_language")
            or r.get("source_language")
            or r.get("lang")
            or LANGUAGES[language]
        )
        detected_name = LANGUAGE_CODES.get(detected_code, detected_code)
        st.session_state["detected_language"] = f"{detected_name} ({detected_code})"
    else:
        st.session_state.pop("new_question", None)
        st.session_state.pop("new_query", None)
        logger.warning(
            "No question-query generated for question=%r, query=%r — reason: %s",
            question,
            query,
            error,
        )
        st.subheader(":red[Error]")
        st.text("Sorry, no question-query pair was generated.")
        st.error(error)

if "new_question" in st.session_state:
    question = st.session_state["question_input"]
    query = st.session_state["query_input"]
    new_question = st.session_state["new_question"]
    new_query = st.session_state["new_query"]
    detected_language = st.session_state.get("detected_language", "")

    col1, col2, col3, _ = st.columns([10, 1, 1, 2])
    with col1:
        st.subheader("Recognized language of original question")
        st.text(detected_language)
    with col2:
        if st.button(
            ":green[OK]", key="detected_language_OK", use_container_width=True
        ):
            submit_feedback(
                question, query, new_question, new_query, "detected_language", "OK"
            )
    with col3:
        if st.button(
            ":red[Wrong!]", key="detected_language_wrong", use_container_width=True
        ):
            submit_feedback(
                question, query, new_question, new_query, "detected_language", "wrong"
            )

    col1, col2, col3, _ = st.columns([10, 1, 1, 2])
    with col1:
        st.subheader("New question")
        st.text(new_question)
    with col2:
        if st.button(":green[OK]", key="new_question_OK", use_container_width=True):
            submit_feedback(question, query, new_question, new_query, "question", "OK")
    with col3:
        if st.button(
            ":red[Wrong!]", key="new_question_wrong", use_container_width=True
        ):
            submit_feedback(
                question, query, new_question, new_query, "question", "wrong"
            )

    col1, col2, col3, _ = st.columns([10, 1, 1, 2])
    with col1:
        st.subheader("New query")
        st.text(new_query)
    with col2:
        if st.button(":green[OK]", key="new_query_OK", use_container_width=True):
            submit_feedback(question, query, new_question, new_query, "query", "OK")
    with col3:
        if st.button(":red[Wrong!]", key="new_query_wrong", use_container_width=True):
            submit_feedback(question, query, new_question, new_query, "query", "wrong")

    # st.divider()

    # Feedback section
    # st.subheader("Feedback")
    # feedback_rating = st.radio(
    #     "How would you rate this transformation?",
    #     ["Please select", "👍 Good", "👎 Not good"],
    #     key="feedback_rating"
    # )

    # feedback_text = st.text_area(
    #     "Additional comments (optional):",
    #     key="feedback_text"
    # )

    # if st.button("Submit feedback", key="submit_feedback"):
    #     if feedback_rating != "Please select":
    #         feedback_data = {
    #             "inputs": [question, query],
    #             "outputs": [r["transformed_question"], r["transformed_query"]],
    #             "rating": 1 if feedback_rating == "👍 Good" else 0
    #         }

    #         try:
    #             feedback_response = requests.post(
    #                 f"{st.session_state.dynbench}/feedback",
    #                 json=feedback_data
    #             )
    #             if feedback_response.status_code == 200:
    #                 st.success("Thank you for your feedback!")
    #             else:
    #                 st.error(f"Failed to submit feedback: {feedback_response.status_code}")
    #         except Exception as e:
    #             st.error(f"Error submitting feedback: {str(e)}")
    #     else:
    #         st.warning("Please select a rating before submitting feedback.")

with open("js/change_menu.js", "r") as f:
    javascript = f.read()
    html(f"<script style='display:none'>{javascript}</script>")


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
