"""
batch_ui.py — the "Benchmark file upload" mode: upload a complete benchmark
file, run every question-query pair through the DynBench backend iteratively,
show a result block per pair (given vs. computed, entities highlighted with a
mouse-over overlay), collect feedback, and export the transformed benchmark in
the exact format of the uploaded file.
"""
import html
import logging
import os
import re

import streamlit as st

from benchmark_formats import FORMATS, BatchResult, parse_benchmark
from utils import call_dynbench, format_sparql, submit_feedback

logger = logging.getLogger(__name__)

DEFAULT_PAIR_LIMIT = 10

_TOOLTIP_CSS = """
<style>
span.entity-mark {
    position: relative;
    border-bottom: 2px dotted #e6a817;
    background: rgba(230, 168, 23, 0.15);
    border-radius: 3px;
    padding: 0 2px;
    cursor: help;
}
span.entity-mark .entity-overlay {
    visibility: hidden;
    opacity: 0;
    transition: opacity 0.15s;
    position: absolute;
    bottom: 125%;
    left: 0;
    z-index: 1000;
    min-width: 220px;
    max-width: 420px;
    background: #262730;
    color: #fafafa;
    border: 1px solid #e6a817;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 0.85rem;
    line-height: 1.4;
    white-space: normal;
}
span.entity-mark:hover .entity-overlay {
    visibility: visible;
    opacity: 1;
}
span.entity-mark .entity-overlay a {
    color: #7fb4f7;
    word-break: break-all;
}
</style>
"""


def _entity_resource_url(entity: str) -> str:
    """Build the knowledge-graph resource URL for an entity like 'wd:Q42'."""
    if not entity:
        return ""
    if entity.startswith(("http://", "https://")):
        return entity
    qid = entity.split(":")[-1]
    return f"https://www.wikidata.org/wiki/{qid}" if qid else ""


def highlight_entity(question: str, label: str, entity: str) -> str:
    """Return HTML of *question* with the entity mention wrapped in a
    mouse-over span whose overlay shows the human-readable label and the
    knowledge-graph resource URL. Falls back to the escaped plain question
    when the label cannot be located in the question text."""
    escaped = html.escape(question)
    if not label:
        return escaped
    match = re.search(re.escape(html.escape(label)), escaped, re.IGNORECASE)
    if not match:
        return escaped
    url = _entity_resource_url(entity)
    link = (
        f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">'
        f"{html.escape(url)}</a>"
        if url
        else ""
    )
    overlay = (
        '<span class="entity-overlay">'
        f"<strong>{html.escape(label)}</strong>"
        + (f" ({html.escape(entity)})" if entity else "")
        + (f"<br>{link}" if link else "")
        + "</span>"
    )
    marked = f'<span class="entity-mark">{match.group(0)}{overlay}</span>'
    return escaped[: match.start()] + marked + escaped[match.end():]


def _selected_replace(result: BatchResult) -> dict:
    if isinstance(result.response, dict):
        return result.response.get("selected_replace") or {}
    return {}


def _render_question(label: str, question: str, entity_label: str, entity: str):
    st.markdown(f"**{label}**")
    st.markdown(
        f"<p style='font-size:115%;'>{highlight_entity(question, entity_label, entity)}</p>",
        unsafe_allow_html=True,
    )


def _render_result_block(result: BatchResult, index: int):
    record = result.record
    with st.container(border=True):
        st.markdown(f"##### Pair `{record.id}`")
        if result.error is not None:
            # given pair + error instead of a computed pair
            col_q, col_s = st.columns(2)
            with col_q:
                _render_question("Given question", record.question, "", "")
            with col_s:
                st.markdown("**Given SPARQL query**")
                st.code(_safe_format(record.query), language="sparql")
            st.error(f"No pair was generated: {result.error}")
            return

        _sr = _selected_replace(result)

        # 1st row: given question | given SPARQL query
        col_q, col_s = st.columns(2)
        with col_q:
            _render_question(
                "Given question",
                record.question,
                _sr.get("old_label", ""),
                _sr.get("old_entity", ""),
            )
        with col_s:
            st.markdown("**Given SPARQL query**")
            st.code(_safe_format(record.query), language="sparql")

        # 2nd row: computed question | computed SPARQL query
        col_q, col_s = st.columns(2)
        with col_q:
            _render_question(
                "Computed question",
                result.new_question,
                _sr.get("new_label", ""),
                _sr.get("new_entity", ""),
            )
        with col_s:
            st.markdown("**Computed SPARQL query**")
            st.code(_safe_format(result.new_query), language="sparql")

        # feedback on the computed pair
        col_ok, col_wrong, _ = st.columns([1, 1, 3])
        with col_ok:
            if st.button(
                ":green[👍 Correct]",
                key=f"batch_ok_{index}",
                use_container_width=True,
                help="The computed question-query pair is CORRECT.",
            ):
                submit_feedback(
                    record.question, record.query,
                    result.new_question, result.new_query,
                    f"batch:{record.id}", "pair", 1,
                )
        with col_wrong:
            if st.button(
                ":red[👎 Wrong]",
                key=f"batch_wrong_{index}",
                use_container_width=True,
                help="The computed question-query pair is INCORRECT.",
            ):
                submit_feedback(
                    record.question, record.query,
                    result.new_question, result.new_query,
                    f"batch:{record.id}", "pair", 0,
                )


def _safe_format(query: str) -> str:
    try:
        return format_sparql(query)
    except Exception:
        return query


def _export_filename(upload_name: str) -> str:
    stem, ext = os.path.splitext(upload_name)
    return f"{stem}-transformed{ext or '.json'}"


def render_batch_mode(transform_url: str, model: str, difficulty: str, language: str):
    """Render the benchmark file-upload mode (called from app.py)."""
    st.markdown(_TOOLTIP_CSS, unsafe_allow_html=True)

    st.write(
        "Upload a complete benchmark file. Every question-query pair is "
        "processed iteratively with the settings from the sidebar, and each "
        "computed pair is shown next to its original for review and feedback."
    )

    with st.expander("Supported benchmark file formats", expanded=False):
        st.markdown(
            "The format is detected automatically from the file name and content:"
        )
        for fmt in FORMATS:
            st.markdown(f"**{fmt.name}** — {fmt.description}")
            st.code(fmt.example)

    uploaded = st.file_uploader(
        "Benchmark file",
        type=["json", "xml", "csv", "tsv", "txt", "rq", "sparql", "ttl", "turtle"],
        help="See 'Supported benchmark file formats' above for the accepted structures.",
    )
    if uploaded is None:
        return

    try:
        fmt, records = parse_benchmark(uploaded.name, uploaded.getvalue())
    except ValueError as exc:
        st.error(str(exc))
        return

    st.success(
        f"Recognized format **{fmt.name}** — {len(records)} question-query "
        f"pair{'s' if len(records) != 1 else ''} found."
    )

    limit = st.number_input(
        "Number of pairs to process (from the beginning of the file)",
        min_value=1,
        max_value=len(records),
        value=min(DEFAULT_PAIR_LIMIT, len(records)),
        help="Each pair is one LLM round-trip (roughly 5–60 seconds), so "
        "processing a complete large benchmark can take a long time.",
    )
    est_minutes = max(1, round(limit * 20 / 60))
    st.caption(
        f"⏱️ Rough estimate: ~{est_minutes} minute{'s' if est_minutes != 1 else ''} "
        f"for {limit} pair{'s' if limit != 1 else ''}."
    )

    run_key = (uploaded.name, uploaded.size, model, difficulty, language, int(limit))
    if st.button(
        f"Process {int(limit)} pair{'s' if limit != 1 else ''} using "
        f"{model.split('/')[-1] if '/' in model else model} 🚀",
        type="primary",
    ):
        results: list[BatchResult] = []
        progress = st.progress(0.0, text="Starting …")
        todo = records[: int(limit)]
        for i, record in enumerate(todo):
            progress.progress(
                i / len(todo),
                text=f"Processing pair {i + 1}/{len(todo)} (id `{record.id}`) …",
            )
            response, error = call_dynbench(
                transform_url, record.question, record.query, model,
                difficulty, language,
            )
            if response:
                results.append(
                    BatchResult(
                        record=record,
                        new_question=response.get("transformed_question"),
                        new_query=response.get("transformed_query"),
                        response=response,
                    )
                )
            else:
                logger.warning("Batch pair %s failed: %s", record.id, error)
                results.append(BatchResult(record=record, error=error))
        progress.progress(1.0, text="Done.")
        st.session_state["batch_results"] = results
        st.session_state["batch_run_key"] = run_key
        st.session_state["batch_format"] = fmt
        st.session_state["batch_upload_name"] = uploaded.name

    results = st.session_state.get("batch_results")
    if not results:
        return
    if st.session_state.get("batch_run_key") != run_key:
        st.info(
            "The shown results below were computed with previous settings or "
            "for a previous file. Click the button above to re-process."
        )

    ok_count = sum(1 for r in results if r.error is None)
    st.subheader(
        f"Results — {ok_count}/{len(results)} pair"
        f"{'s' if len(results) != 1 else ''} computed"
    )

    fmt = st.session_state.get("batch_format")
    if fmt is not None and ok_count:
        exported = fmt.export(results)
        st.download_button(
            f"⬇️ Download transformed benchmark ({fmt.name})",
            data=exported.encode("utf-8"),
            file_name=_export_filename(st.session_state.get("batch_upload_name", uploaded.name)),
            help="The computed pairs in the exact same file format as the upload.",
        )

    for i, result in enumerate(results):
        _render_result_block(result, i)
