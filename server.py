import requests
from decouple import Config, RepositoryEnv

import streamlit as st

from PIL import Image
import base64


PAGE_TITLE = 'DynBench: robust benchmark records generator'
PAGE_IMAGE = 'images/dynbench.png'

LANGUAGES = {
    'English': 'en',
    'German':  'de',
    'French':  'fr',
    'Russian': 'ru',
    'Ukrainian': 'uk',
    'Italian': 'it',
    'Spanish': 'es',
    'Polish': 'pl',
    'Romanian': 'ro',
    'Dutch': 'nl',
    'Turkish': 'tr',
    'Bavarian': 'bar',
    'Portuguese': 'pt',
    'Hungarian': 'hu',
    'Greek': 'el',
    'Czech': 'cs',
    'Swedish': 'sv',
    'Catalan': 'ca',
    'Serbian': 'sr',
    'Bulgarian': 'bg',
}

VALUES = [
    {
        'question': 'What is the highest mountain in Germany?',
        'query': 'SELECT ?uri WHERE { ?uri wdt:P31 wd:Q8502 ; wdt:P2044 ?elevation ; wdt:P17 wd:Q183 . } ORDER BY DESC(?elevation) LIMIT 1',
    },
]


def call_dynbench(url, question, query, model, complexity='normal', language='en'):
    headers = {}
    data = {
        'question': question,
        'query': query,
        'model': model,
        'lang': language,
        'complexity': complexity,
    }

    r = requests.post(url, headers=headers, json=data)

    if r and r.status_code == 200:
        return r.json()
    else:
        return None


config = Config(RepositoryEnv('config.env'))

if 'bearer' not in st.session_state:
    st.session_state.dynbench = config('DYNBENCH')


st.set_page_config(
    layout="wide",
    page_title=PAGE_TITLE,
    # page_icon=Image.open(PAGE_ICON)
)

# --- Sidebar ---
with st.sidebar:
    with open(PAGE_IMAGE, "rb") as f:
    # Read the optional file VERSION.txt containing version number

        image_data = base64.b64encode(f.read()).decode("utf-8")
        st.sidebar.markdown(
            f"""
            <div style="display:table;margin-top:-10%;margin-bottom:15%;margin-left:auto;margin-right:auto;text-align:center">
                <img src="data:image/png;base64,{image_data}" class="app_logo"></a>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.title("Settings")

    difficulty = st.radio(
        "Select difficulty:",
        ["easy", "normal", "hard", "random"],
    )

    language = st.radio(
        "Select language:",
        list(LANGUAGES),
    )

# --- Main panel ---
st.title("Generate new question-query pair")

col1, col2 = st.columns(2)

with col1:
    question = st.text_input("Question", value=VALUES[0]['question'])
with col2:
    query = st.text_input("SPARQL query", value=VALUES[0]['query'])

submit = st.button("Generate")

# --- Output fields ---
st.subheader("Output")

# output_1 = st.text_area('New question', value='', height=80, disabled=True)
# output_2 = st.text_area('New query', value='', height=80, disabled=True)

if submit:
    print(st.session_state.dynbench)
    print(question)
    print(query)

    r = call_dynbench(st.session_state.dynbench, question, query, 'gpt-4o', difficulty, LANGUAGES[language])
    # r = call_dynbench(st.session_state.dynbench, question, query, 'mistral-small')

    if r:
        st.subheader('New question')
        st.text(r['transformed_question'])
        st.subheader('New query')
        st.text(r['transformed_query'])
    else:
        st.text('No question-query generated')



