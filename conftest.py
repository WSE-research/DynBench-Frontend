"""Test configuration.

The application's settings module reads MODEL and DYNBENCH from the environment
with no defaults (in production they are provided via config.env / the container).
Provide harmless defaults here so the unit tests import cleanly without a live
deployment. Real values, when present in the environment, take precedence.
"""
import os

os.environ.setdefault("MODEL", "gpt-4o")
os.environ.setdefault("DYNBENCH", "http://localhost:40128")
