import os
import logging
import requests
import json
import random

from decouple import config

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


MODEL = config('MODEL')
GITHUB_REPO = config(
    "GITHUB_REPO", "https://github.com/WSE-research/DynBench-Frontend.git"
)

PAGE_TITLE = 'DynBench: robust benchmark records generator'
PAGE_ICON  = 'images/dynbench-icon-64.png'
PAGE_IMAGE = 'images/dynbench-logo-alpha.png'

LANGUAGES = {
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

LANG_BACK = {i: j for i, j in zip(LANGUAGES.values(), LANGUAGES.keys())}


VALUES = [
    {
        "question": "What is the highest mountain in Germany?",
        "query": "SELECT ?uri WHERE { ?uri wdt:P31 wd:Q8502 ; wdt:P2044 ?elevation ; wdt:P17 wd:Q183 . } ORDER BY DESC(?elevation) LIMIT 1",
    },
]


def call_dynbench(url, question, query, model, complexity="normal", language="en"):
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
        r = requests.post(url, headers=headers, json=data)
        if r and r.status_code == 200:
            return r.json()
        else:
            return None
    except:
        return None
    

if 'dynbench' not in st.session_state:
    st.session_state['dynbench'] = config("DYNBENCH")

    with open('benchmarks/DynQALD.json', 'r') as f:
        st.session_state.samples = json.load(f)

    st.session_state.languages = sorted(list({i['language'] for i in st.session_state.samples}))
    for lang in st.session_state.languages:
        st.session_state[f'checkbox_{lang}'] = True

    st.session_state.random_record = random.choice(st.session_state.samples)
    st.session_state.question_input = st.session_state.random_record["question"]
    st.session_state.query_input = st.session_state.random_record["query"]


st.set_page_config(
    layout="wide",
    page_title=PAGE_TITLE,
    page_icon=Image.open(PAGE_ICON)
)

with open("css/style_menu_logo.css") as f, open("css/style_github_ribbon.css") as g:
    st.markdown(f"<style>{f.read()}{g.read()}</style>", unsafe_allow_html=True)

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

    difficulty = st.radio(
        "Select difficulty for the new question:",
        ["easy", "normal", "hard", "random"],
        help='**Options are:**\n- Easy: possible highest PageRank\n- Normal: same as the original\n- Hard: possible lowest PageRank\n- Random: any compatible',
    )

    # --- Original language(S) selector ---
    st.markdown(
        '<style>div[data-testid="stCheckbox"]{margin-bottom: -10px;}</style>', 
        unsafe_allow_html=True
    )
    st.markdown(
        '<span style="font-size:14px; font-weight:400; margin-bottom: 4px;">Select language(s) for random record</span>',
        unsafe_allow_html=True,
        help="Select language(s) you'd like to see for a random sample.",
    )
    for lang in st.session_state.languages:
        st.checkbox(LANG_BACK[lang], key=f'checkbox_{lang}')
    st.space("small")

    # language = st.radio(
    language = st.selectbox(
        "Select language for the new question:",
        list(LANGUAGES),
    )


# --- Main panel ---
col_titel, col_random = st.columns([4, 1], vertical_alignment='bottom')
with col_titel:
    st.title("Generate new question-query pair")
with col_random:
    if st.button('Random sample'):
        selected = {lang for lang in st.session_state.languages if st.session_state[f'checkbox_{lang}']}
        # st.write(selected)
        slice = [i for i in st.session_state.samples if i['language'] in selected]

        st.session_state.random_record = random.choice(slice)
        st.session_state.question_input = st.session_state.random_record["question"]
        st.session_state.query_input = st.session_state.random_record["query"]
        st.rerun()        

col1, col2 = st.columns([2, 3])

with col1:
    st.text_input("Question", key='question_input')

with col2:
    st.text_input("SPARQL query", key='query_input')

submit = st.button("Generate")


def submit_feedback(question, query, new_question, new_query, object, feedback):
    pass


if submit:
    question = st.session_state.question_input
    query = st.session_state.query_input

    logger.info(f'Run new generation for question {question}')
    logger.info(f'Query: {query}')

    r = call_dynbench(
        st.session_state.dynbench,
        question,
        query,
        MODEL,
        difficulty,
        LANGUAGES[language],
    )

    if r and r.get('transformed_question', None) and r.get('transformed_query', None):
        st.session_state['new_question'] = r['transformed_question']
        st.session_state['new_query'] = r['transformed_query']
    else:
        st.session_state.pop('new_question', None)
        st.session_state.pop('new_query', None)
        logger.warning(
            "No question-query generated for question=%r, query=%r", question, query
        )
        st.subheader(':red[Error]')
        st.text('Sorry, an error occurred. No question-query pair was generated.')
        st.text('Please try again with different settings or new question/query.')

if 'new_question' in st.session_state:
    question = st.session_state['question_input']
    query = st.session_state['query_input']
    new_question = st.session_state['new_question']
    new_query = st.session_state['new_query']

    col1, col2, col3, _ =  st.columns([10, 1, 1, 2])
    with col1:
        st.subheader("New question")
        st.text(new_question)
    with col2:
        if st.button(':green[✔]', key='new_question_OK', use_container_width=True):
            submit_feedback(question, query, new_question, new_query, 'question', 'OK')
    with col3:
        if st.button(':red[✗]', key='new_question_wrong', use_container_width=True):
            submit_feedback(question, query, new_question, new_query, 'question', 'wrong')

    col1, col2, col3, _ =  st.columns([10, 1, 1, 2])
    with col1:
        st.subheader("New query")
        st.text(new_query)
    with col2:
        if st.button(':green[✔]', key='new_query_OK', use_container_width=True):
            submit_feedback(question, query, new_question, new_query, 'query', 'OK')
    with col3:
        if st.button(':red[✗]', key='new_query_wrong', use_container_width=True):
            submit_feedback(question, query, new_question, new_query, 'query', 'wrong')


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
