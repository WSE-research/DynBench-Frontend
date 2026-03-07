import os
import logging
import requests
import json
import random

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


MODEL = config('MODEL')
GITHUB_REPO = config(
    "GITHUB_REPO", "https://github.com/WSE-research/DynBench-Frontend.git"
)

PAGE_TITLE = 'DynBench: robust benchmark records generator'
# PAGE_IMAGE = 'images/dynbench.png'
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
    

# config = Config(RepositoryEnv("config.env"))

if 'dynbench' not in st.session_state:
    st.session_state['dynbench'] = config("DYNBENCH")
    logger.info(f'Dynbench URL: {st.session_state.dynbench}')

    with open('benchmarks/DynQALD.json', 'r') as f:
        st.session_state.samples = json.load(f)
    st.session_state.random_record = random.choice(st.session_state.samples)


st.set_page_config(
    layout="wide",
    page_title=PAGE_TITLE,
    # page_icon=Image.open(PAGE_ICON)
)

with open("css/style_menu_logo.css") as f, open("css/style_github_ribbon.css") as g:
    st.markdown(f"<style>{f.read()}{g.read()}</style>", unsafe_allow_html=True)

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
        "Select difficulty for the new question:",
        ["easy", "normal", "hard", "random"],
        help='- Highest PageRank\n- Same as the original\n- Lowest PageRank\n- Any compatible'
    )

    language = st.radio(
        "Select language for the new question:",
        list(LANGUAGES),
    )


# --- Main panel ---
col_titel, col_random = st.columns([4, 1])
with col_titel:
    st.title("Generate new question-query pair")
with col_random:
    if st.button('Random sample'):
        st.session_state.random_record = random.choice(st.session_state.samples)
        st.rerun()
        

col1, col2 = st.columns(2)

with col1:
    # question = st.text_input("Question", value=VALUES[0]["question"], key='question_input')
    st.session_state.question_input = st.session_state.random_record["question"]
    st.text_input("Question", key='question_input')

with col2:
    # query = st.text_input("SPARQL query", value=VALUES[0]["query"], key='query_input')
    st.session_state.query_input = st.session_state.random_record["query"]
    st.text_input("SPARQL query", key='query_input')

submit = st.button("Generate")

# --- Output fields ---
# st.subheader("Output")

# output_1 = st.text_area('New question', value='', height=80, disabled=True)
# output_2 = st.text_area('New query', value='', height=80, disabled=True)

def submit_feedback(question, query, new_question, new_query, object, feedback):
    pass


if submit:
    question = st.session_state.question_input
    query = st.session_state.query_input

    logger.info('Run new generation for question {question}')
    # logger.info("Question: %s", question)
    # logger.info("Query: %s", query)

    # call_dynbench(url, question, query, model, complexity="normal", language="en")

    r = call_dynbench(
        st.session_state.dynbench,
        question,
        query,
        # st.session_state.question_input,
        # st.session_state.query_input,
        MODEL,
        difficulty,
        LANGUAGES[language],
    )
    # r = call_dynbench(st.session_state.dynbench, question, query, 'mistral-small')

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
