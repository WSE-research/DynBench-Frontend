import streamlit as st
import requests
from decouple import Config, RepositoryEnv


LANGUAGES = {
    'English': 'en',
    'German':  'de',
    'French':  'fr',
    'Russian': 'ru',
    'Ukrainian': 'uk',
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


config = Config(RepositoryEnv('.env'))

if 'bearer' not in st.session_state:
    print(config('DYNBENCH'))
    st.session_state.dynbench = config('DYNBENCH')

st.set_page_config(layout="wide")

# --- Sidebar ---
st.sidebar.title("Settings")

difficulty = st.sidebar.radio(
    "Select difficulty:",
    ["easy", "normal", "hard", "random"],
)

language = st.sidebar.radio(
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



