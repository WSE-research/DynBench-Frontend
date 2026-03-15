"""
Entry point for the DynBench Frontend.

Importing healthcheck before bootstrap.run() patches Server._create_app so
that the /health route is registered on Streamlit's Tornado server at startup,
without requiring a separate port.
"""
import healthcheck  # noqa: F401 — must be imported before bootstrap.run()
import api          # noqa: F401 — must be imported before bootstrap.run()

from streamlit.web.bootstrap import run

if __name__ == "__main__":
    run(
        main_script_path="server.py",
        is_hello=False,
        args=[],
        flag_options={"server.address": "0.0.0.0"},
    )
