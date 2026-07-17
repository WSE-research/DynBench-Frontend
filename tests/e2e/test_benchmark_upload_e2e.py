"""End-to-end tests for the benchmark upload — one per supported file format.

For every supported benchmark file type a small subset extracted from the
ORIGINAL benchmark file (see fixtures/README.md) is sent through the real
server (booted via run.py, DynBench backend mocked) using the batch API, and
the exported result is validated to be in the correct, identical file format:
the export must be auto-detected as the same format, parse into the processed
pairs, and preserve the structure of the original records.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmark_formats import parse_benchmark  # noqa: E402

from mock_dynbench_backend import MOCK_PREFIX, start as start_mock_backend  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.e2e

# (fixture file, expected detected format, records in fixture)
CASES = [
    ("qald-9-test.subset.json", "QALD JSON", 2),
    ("beastiary-qald-format.subset.json", "QALD JSON", 2),
    ("qald-4-biomedical-train.subset.xml", "QALD XML", 2),
    ("lcquad1-train.subset.json", "LC-QuAD 1.0", 2),
    ("lcquad2-test.subset.json", "LC-QuAD 2.0", 2),
    ("rubq-2.0-test.subset.json", "RuBQ", 2),
    ("grailqa-validation.subset.json", "GrailQA", 2),
    ("complexwebquestions-validation.subset.json", "JSON list (question + sparql)", 2),
    ("webqsp-test.subset.json", "WebQuestionsSP", 2),
    ("dynqald.subset.json", "DynBench JSON", 2),
    ("spider4sparql-dev.subset.csv", "CSV / TSV", 2),
    ("bio-soda-bgee-q1.rq", "SPARQL file (.rq/.sparql)", 1),
    ("sib-uniprot-100.ttl", "SIB sparql-examples (Turtle)", 1),
]

# JSON-list formats whose export must preserve the exact record structure
_KEY_PRESERVING = {
    "LC-QuAD 1.0",
    "LC-QuAD 2.0",
    "RuBQ",
    "GrailQA",
    "JSON list (question + sparql)",
}


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def app_server():
    """The real server (Streamlit + REST API via run.py) with a mocked backend."""
    mock_server, mock_url = start_mock_backend()
    port = _free_port()
    env = {
        **os.environ,
        "MODEL": "mock/model-a",
        "DYNBENCH": mock_url,
        "PORT": str(port),
        "STREAMLIT_SERVER_HEADLESS": "true",
    }
    proc = subprocess.Popen(
        [sys.executable, "run.py"], cwd=REPO_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read() if proc.stdout else ""
                pytest.fail(f"server exited early (code {proc.returncode}):\n{out[-2000:]}")
            try:
                if requests.get(f"{base}/_stcore/health", timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("server never became healthy")
        yield base
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()


def _upload(app_server, filename, content, **params):
    return requests.post(
        f"{app_server}/api/transform-benchmark",
        params={"model": "mock/model-a", "limit": 0, **params},
        files={"file": (filename, content)},
        timeout=60,
    )


@pytest.mark.parametrize(
    "fixture,expected_format,expected_records",
    CASES,
    ids=[c[0] for c in CASES],
)
def test_upload_processes_and_exports_same_format(
    app_server, fixture, expected_format, expected_records
):
    content = (FIXTURES / fixture).read_bytes()
    _, original_records = parse_benchmark(fixture, content)
    assert len(original_records) == expected_records  # fixture sanity

    # --- 1) JSON report: every pair processed via the mocked backend --------
    resp = _upload(app_server, fixture, content)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["format"] == expected_format
    assert report["total_pairs"] == expected_records
    assert report["processed"] == report["succeeded"] == expected_records
    assert report["failed"] == 0
    for result in report["results"]:
        assert result["transformed_question"].startswith(MOCK_PREFIX)
        assert result["transformed_query"].startswith(MOCK_PREFIX)
        assert result["selected_replace"]["new_entity"] == "wd:Q142714"

    # --- 2) file export: correct data format, identical to the upload -------
    resp = _upload(app_server, fixture, content, response="file")
    assert resp.status_code == 200, resp.text
    disposition = resp.headers.get("Content-Disposition", "")
    assert "-transformed" in disposition
    export_name = disposition.split('filename="')[1].rstrip('"')
    assert Path(export_name).suffix == Path(fixture).suffix or Path(fixture).suffix == ""

    # the export must be auto-detected as the SAME format and parse cleanly
    fmt, exported_records = parse_benchmark(export_name, resp.content)
    assert fmt.name == expected_format
    assert len(exported_records) == expected_records
    for record in exported_records:
        assert record.question.startswith(MOCK_PREFIX)
        assert record.query.startswith(MOCK_PREFIX)

    # structure preservation for the flat JSON-list formats: the exported
    # records keep exactly the fields of the original records
    if expected_format in _KEY_PRESERVING:
        exported_doc = json.loads(resp.content)
        original_doc = json.loads(content)
        assert [set(item) for item in exported_doc] == [
            set(item) for item in original_doc
        ]


def test_upload_error_for_unsupported_file(app_server):
    resp = _upload(app_server, "notes.txt", b"no benchmark structure at all")
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["error"]
