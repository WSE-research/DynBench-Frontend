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

    logger.debug("Backend response keys: %s", list(body.keys()))

    # Find the best attempt (first success, or last attempt as fallback).
    _attempt = next(
        (a for a in body.get("attempts", []) if a.get("Status") == "success"),
        (body.get("attempts") or [None])[-1],
    )

    # Normalise: some backend versions return the result inside the `attempts`
    # list with title-case keys rather than as top-level snake_case keys.
    # Promote the values so the rest of the application can always rely on
    # `body["transformed_question"]` and `body["transformed_query"]`.
    if not body.get("transformed_question") and _attempt:
        body["transformed_question"] = _attempt.get("Transformed question", "")
    if not body.get("transformed_query") and _attempt:
        body["transformed_query"] = _attempt.get("Transformed query", "")

    # Normalise selected_replace: build it from the successful attempt's fields
    # when it is absent at the top level.
    if not body.get("selected_replace") and _attempt:
        body["selected_replace"] = {
            "old_entity":   _attempt.get("Original entity", ""),
            "new_entity":   _attempt.get("New entity", ""),
            "old_label":    _attempt.get("Label for original entity", ""),
            "new_label":    _attempt.get("Label for new entity", ""),
            "old_pagerank": _attempt.get("Original entity PageRank", ""),
            "new_pagerank": _attempt.get("New entity PageRank", ""),
        }

    logger.info(
        "call_dynbench result: transformed_question=%r selected_replace=%r",
        (body.get("transformed_question") or "")[:80],
        body.get("selected_replace"),
    )

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


def output_row(label, value, key, question, query, new_question, new_query, format=None):
    """Render a labelled output text with OK / Wrong! feedback buttons.

    Args:
        format: Optional display format for the value. Pass ``"sparql"`` to
                render the value as a syntax-highlighted SPARQL code block.
                ``None`` (default) renders the value as styled plain text.
    """
    with st.container(key=f"output_row_{key}"):
        st.markdown(f"**{label}:**")
        col_text, col_btns = st.columns([6, 4], vertical_alignment="top")
        with col_text:
            if format == "sparql":
                st.code(value, language="sparql")
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
