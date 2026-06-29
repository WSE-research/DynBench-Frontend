"""End-to-end smoke test: boot the Streamlit server and confirm it serves."""
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
APP = "app.py"

pytestmark = pytest.mark.e2e


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _app_env():
    return {
        **os.environ,
        "MODEL": "gpt-4o",
        "DYNBENCH": "http://localhost:40128",
        "UPLOAD_DIRECTORY": tempfile.mkdtemp(prefix="dynbench-e2e-"),
    }


def test_streamlit_server_serves_health():
    port = _free_port()
    cmd = [
        sys.executable, "-m", "streamlit", "run", APP,
        "--server.headless=true",
        f"--server.port={port}",
        "--server.address=127.0.0.1",
        "--browser.gatherUsageStats=false",
    ]
    proc = subprocess.Popen(
        cmd, cwd=REPO_ROOT, env=_app_env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 120
        healthy = False
        while time.time() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read() if proc.stdout else ""
                pytest.fail(f"streamlit exited early (code {proc.returncode}):\n{out[-2000:]}")
            try:
                r = requests.get(f"{base}/_stcore/health", timeout=2)
                if r.status_code == 200 and r.text.strip().lower() == "ok":
                    healthy = True
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        assert healthy, "Streamlit /_stcore/health never became ok"
        root = requests.get(f"{base}/", timeout=10)
        assert root.status_code == 200
        assert b"<title>" in root.content
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
