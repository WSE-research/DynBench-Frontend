"""
utils.py — shared utility functions and UI helpers for server.py.
"""
import logging
import random

import requests
import sparqlib
import streamlit as st

logger = logging.getLogger(__name__)

_FEEDBACK_MESSAGES = [
    "Thank you for helping us improve DynBench — every data point counts! 🌟",
    "Your contribution makes DynBench stronger for the whole research community! 💪",
    "High five! Your feedback is shaping the future of benchmarking! 🙌",
    "You're a benchmarking hero! Thanks for taking the time to contribute! 🦸",
    "Awesome! Your input helps us build a more robust benchmark! 🚀",
    "Thank you! The community is better because of contributors like you! 🎯",
    "Brilliant! Your feedback keeps DynBench sharp and accurate! ⚡",
    "You just made science a little better — thank you! 🔬",
    "Amazing contribution! Your feedback fuels continuous improvement! 🔥",
    "Cheers to you! Every piece of feedback brings us closer to perfection! 🏆",
]


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


def submit_feedback(question, query, new_question, new_query, object, feedback):
    logger.info(f"Submit feedback for {object}: {feedback}")
    st.session_state["feedback_count"] = st.session_state.get("feedback_count", 0) + 1
    st.toast(random.choice(_FEEDBACK_MESSAGES), icon="🎉")
    if st.session_state["feedback_count"] % 3 == 0:
        st.balloons()


def output_row(label, value, key, question, query, new_question, new_query, is_formatted=False):
    """Render a labelled output text with OK / Wrong! feedback buttons."""
    with st.container(key=f"output_row_{key}"):
        st.markdown(f"**{label}:**")
        col_text, col_btns = st.columns([6, 4], vertical_alignment="top")
        with col_text:
            if is_formatted:
                value = value.replace("\n", "<br>")
                value = value.replace(" ", "&nbsp;")
                st.markdown(value, unsafe_allow_html=True)
            else:
                st.markdown(
                    f"<p style='font-size: 125%;'>{value}</p>", unsafe_allow_html=True
                )
            st.markdown(
                "<span class='placeholder' style='display:none;'></span>",
                unsafe_allow_html=True,
            )
        with col_btns:
            col_ok, col_wrong = st.columns(2, vertical_alignment="top")
            with col_ok:
                if st.button(
                    ":green[👍 Correct]",
                    key=f"{key}_OK",
                    width="stretch",
                    help="The generated data is CORRECT.",
                ):
                    submit_feedback(question, query, new_question, new_query, key, "OK")
            with col_wrong:
                if st.button(
                    ":red[👎 Wrong]",
                    key=f"{key}_Wrong",
                    width="stretch",
                    help="The generated data is INCORRECT.",
                ):
                    submit_feedback(question, query, new_question, new_query, key, "wrong")
