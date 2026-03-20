import os
import logging
import json
import random

from enum import Enum

from decouple import config

import colorlog
import streamlit as st
from streamlit.components.v1 import html

from PIL import Image
import base64

from wse_logo_rotation import start_wse_logo_rotation, stop_wse_logo_rotation
import healthcheck
from sample_selector import (
    select_sample,
    build_samples_by_id,
    build_samples_by_language,
)
from utils import call_dynbench, output_row, format_sparql, submit_feedback
from settings import *

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


st.set_page_config(
    layout="wide",
    page_title=PAGE_TITLE,
    page_icon=Image.open(PAGE_IMAGE),
)

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


# def call_dynbench(url, question, query, model, complexity="normal", language="en"):
#     headers = {}
#     data = {
#         "question": question,
#         "query": query,
#         "model": model,
#         "lang": language,
#         "complexity": complexity,
#         "checks": ["sentence"],
#     }

#     try:
#         r = requests.post(url, headers=headers, json=data)
#         if r and r.status_code == 200:
#             return r.json()
#         else:
#             return None
#     except:
#         return None
    

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

    st.title("Settings")

    # difficulty = st.radio(
    #     "Select difficulty for the new question:",
    #     ["easy", "normal", "hard", "random"],
    #     help='**Options are:**\n- Easy: possible highest PageRank\n- Normal: same as the original\n- Hard: possible lowest PageRank\n- Random: any compatible',
    # )

    difficulty = st.radio(
        "Select difficulty for the entities in the generated question-query pair:",
        ["easy", "similar", "hard", "random"],
        index=1,
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
        # st.error(f"Backend unreachable: {_backend_status['message']}", icon="🚨")

    # # --- Original language(S) selector ---
    # st.markdown(
    #     '<style>div[data-testid="stCheckbox"]{margin-bottom: -10px;}</style>', 
    #     unsafe_allow_html=True
    # )
    # st.markdown(
    #     '<span style="font-size:14px; font-weight:400; margin-bottom: 4px;">Select language(s) for random record</span>',
    #     unsafe_allow_html=True,
    #     help="Select language(s) you'd like to see for a random sample.",
    # )
    # for lang in st.session_state.languages:
    #     st.checkbox(LANG_BACK[lang], key=f'checkbox_{lang}')
    # st.space("small")

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
# col_titel, col_random = st.columns([4, 1], vertical_alignment='bottom')
# with col_titel:
#     st.title("Generate new question-query pair")
# with col_random:
#     if st.button('Random sample'):
#         st.session_state.pop('new_question', None)
#         selected = {lang for lang in st.session_state.languages if st.session_state[f'checkbox_{lang}']}
#         # st.write(selected)
#         slice = [i for i in st.session_state.samples if i['language'] in selected]

#         st.session_state.random_record = random.choice(slice)
#         st.session_state.question_input = st.session_state.random_record["question"]
#         st.session_state.query_input = st.session_state.random_record["query"]
#         st.rerun()        

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
        f"Generate using {MODEL} 🚀",
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

    start_wse_logo_rotation()

    with st.spinner(
        "Generating question-query pair using " + MODEL + "...", show_time=True
    ):
        r, error = call_dynbench(
            st.session_state.transform_url,
            question,
            query,
            MODEL,
            difficulty,
            LANGUAGES[language],
        )

        print(r)

    stop_wse_logo_rotation()

    # if r:
    #     st.session_state['new_question'] = r['transformed_question']
    #     st.session_state['new_query'] = r['transformed_query']
    #     st.session_state.result = r
    # else:
    #     st.session_state.pop('new_question', None)
    #     st.session_state.pop('new_query', None)
    #     logger.warning(
    #         "No question-query generated for question=%r, query=%r", question, query
    #     )
    #     st.subheader(':red[Error]')
    #     st.text('Sorry, an error occurred. No question-query pair was generated.')
    #     st.text('Please try again with different settings or new question/query.')

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
    # col1, col2, col3, _ =  st.columns([10, 1, 1, 2])
    # with col1:
    #     st.subheader("New question")
    #     st.text(new_question)
    # with col2:
    #     if st.button(':green[✔]', key='new_question_OK', use_container_width=True):
    #         submit_feedback(question, query, new_question, new_query, 'question', 'OK')
    # with col3:
    #     if st.button(':red[✗]', key='new_question_wrong', use_container_width=True):
    #         submit_feedback(question, query, new_question, new_query, 'question', 'wrong')

    # col1, col2, col3, _ =  st.columns([10, 1, 1, 2])
    # with col1:
    #     st.subheader("New query")
    #     st.text(new_query)
    # with col2:
    #     if st.button(':green[✔]', key='new_query_OK', use_container_width=True):
    #         submit_feedback(question, query, new_question, new_query, 'query', 'OK')
    # with col3:
    #     if st.button(':red[✗]', key='new_query_wrong', use_container_width=True):
    #         submit_feedback(question, query, new_question, new_query, 'query', 'wrong')

    st.divider()

#    with st.expander("See more details"):
#        for attempt in st.session_state.result['extra']['attempts']:
#            if attempt.get('Status', 'failed') == 'success':
#                for k, v in attempt.items():
#                    st.write(f'{k}: {v}')
#
#        for attempt in st.session_state.result['extra']['attempts']:
#            if attempt.get('Status', 'failed') != 'success':
#                with st.expander(":red[Failed attempt]"):
#                    for k, v in attempt.items():
#                        st.write(f'{k}: {v}')
        # replace = st.session_state.result['extra']['selected_replace']
        # replaces = st.session_state.result['extra']['total_candidates']
        # st.write(f"Original language: {st.session_state.result['extra']['Original language']}")
        # st.write(f"Original entity: {replace['old_entity']} ({replace['old_label']})")
        # st.write(f"Replace entity: {replace['new_entity']} ({replace['new_label']})")
        # st.write(f"Original entity PageRank: {replace['old_pagerank']}")
        # st.write(f"Replace entity PageRank: {replace['new_pagerank']}")
        # st.write(f"Potential replacements found: {replaces}")

# add some vertical space
st.write("")
st.write("")

with st.expander("API request (curl)"):
    _curl_payload = {
        "question": st.session_state.get("question_input", ""),
        "query": st.session_state.get("query_input", ""),
        "model": MODEL,
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
                    _display_value = sparqlib.format_string(str(_raw_value))
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
