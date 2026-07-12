"""AppTest coverage for the usage-mode selection flow in app.py:
landing page (centered selector, no sidebar selector), the three usage modes
(one question+query, file upload, RESTful API), and the mode tag in the title.
"""
from streamlit.testing.v1 import AppTest


def _app():
    return AppTest.from_file("app.py", default_timeout=60)


def _markdown_text(at):
    return " ".join(str(m.value) for m in at.markdown)


def _sidebar_mode_radio(at):
    return [r for r in at.radio if r.key == "_usage_mode_radio"]


# --- landing page (no stored preference) --------------------------------------

def test_landing_shows_centered_selector():
    at = _app().run()
    assert not at.exception
    button_keys = {b.key for b in at.button}
    assert {"choose_single", "choose_batch", "choose_api"} <= button_keys


def test_landing_shows_plain_title_without_mode_tag():
    at = _app().run()
    assert any("DynBench: Question-Query Pair Generator" in str(t.value) for t in at.title)
    md = _markdown_text(at)
    assert "one question+query</span>" not in md  # no mode tag yet


def test_landing_hides_sidebar_selector_and_mode_uis():
    at = _app().run()
    assert not _sidebar_mode_radio(at)  # selector only in the center
    assert "Reference question" not in [t.label for t in at.text_area]
    assert "Settings" not in " ".join(str(t.value) for t in at.title)


# --- mode: one question+query --------------------------------------------------

def test_single_mode_shows_ui_and_current_mode_tag():
    at = _app().run()
    at.button(key="choose_single").click().run()
    assert not at.exception
    assert "Reference question" in [t.label for t in at.text_area]
    md = _markdown_text(at)
    assert "one question+query" in md  # tag-like label in the title
    assert _sidebar_mode_radio(at)  # sidebar selector visible now


def test_single_mode_difficulty_options_have_icons_but_raw_values():
    at = _app().run()
    at.button(key="choose_single").click().run()
    difficulty = [r for r in at.radio if r.key != "_usage_mode_radio"][0]
    # displayed options carry the recognition icons ("similar" = approx symbol) …
    assert list(difficulty.options) == ["🟢 easy", "≈ similar", "🔴 hard", "🎲 random"]
    # … while the Python-side VALUE stays the raw option (API contract)
    assert difficulty.value == "similar"


# --- mode: file upload ----------------------------------------------------------

def test_batch_mode_shows_tag_description_and_no_single_ui():
    at = _app().run()
    at.button(key="choose_batch").click().run()
    assert not at.exception
    md = _markdown_text(at)
    assert "file upload" in md  # tag-like label in the title
    assert "What is this mode for?" in md  # extensive purpose description
    assert "memorize" in md
    assert "Reference question" not in [t.label for t in at.text_area]


# --- mode: RESTful API -----------------------------------------------------------

def test_api_mode_points_to_openapi_description():
    at = _app().run()
    at.button(key="choose_api").click().run()
    assert not at.exception
    md = _markdown_text(at)
    assert "RESTful API" in md  # tag-like label in the title
    assert "/api/openapi.json" in md
    assert "/api/transform-benchmark" in md  # covers both usage modes
    # model/difficulty settings are not relevant in API mode
    assert not [r for r in at.radio if r.key != "_usage_mode_radio"]


# --- switching via the sidebar selector ------------------------------------------

def test_sidebar_selector_switches_mode():
    at = _app().run()
    at.button(key="choose_single").click().run()
    radio = _sidebar_mode_radio(at)[0]
    at = radio.set_value("batch").run()
    assert not at.exception
    md = _markdown_text(at)
    assert "What is this mode for?" in md
    assert "Reference question" not in [t.label for t in at.text_area]
