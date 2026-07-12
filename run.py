"""
Entry point for the DynBench Frontend.

Importing healthcheck before bootstrap.run() patches Server._create_app so
that the /health route is registered on Streamlit's Tornado server at startup,
without requiring a separate port.
"""
import os

import healthcheck  # noqa: F401 — must be imported before bootstrap.run()
import api          # noqa: F401 — must be imported before bootstrap.run()

from streamlit.web import bootstrap

if __name__ == "__main__":
    flag_options = {
        "server.address": os.environ.get("ADDRESS", "0.0.0.0"),
        "server.port": int(os.environ.get("PORT", "8501")),
    }
    # bootstrap.run() does NOT apply flag_options itself — the streamlit CLI
    # loads them separately, and STREAMLIT_* env vars only work through the
    # CLI as well. Without this call the options are silently ignored.
    bootstrap.load_config_options(flag_options=flag_options)
    bootstrap.run(
        main_script_path="app.py",
        is_hello=False,
        args=[],
        flag_options=flag_options,
    )
