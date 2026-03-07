"""
sample_selector.py — pure selection logic for benchmark samples.

Keeps all Streamlit state manipulation out of this module so the logic
can be unit-tested without any Streamlit dependency.
"""

import random
from typing import Optional

import logging

logger = logging.getLogger(__name__)


def select_sample(
    samples: list[dict],
    samples_by_id: dict[str, list[dict]],
    samples_by_language: dict[str, list[dict]],
    sample_id: Optional[str],
    sample_language: Optional[str],
    random_fallback: bool = False,
) -> Optional[dict]:
    """Select a benchmark sample according to the given request parameters.

    Precedence rules
    ----------------
    both present
        Return a random entry that matches *both* ``sample_id`` and
        ``sample_language``.  ``None`` if no such entry exists.
    only ``sample_id``
        Return a random language variant of the entry with that ID.
        ``None`` if the ID is unknown.
    only ``sample_language``
        Return a random entry whose ``language`` field equals
        ``sample_language``.  ``None`` if the language is unknown.
    neither + ``random_fallback=True``
        Return a random entry from the full ``samples`` list.
        ``None`` if ``samples`` is empty.
    neither + ``random_fallback=False`` (default)
        Return ``None`` — the caller decides (e.g. the "Random sample"
        button has not been clicked yet).
    """
    logger.info(
        "Selecting sample with id=%r and language=%r", sample_id, sample_language
    )

    if sample_id is not None and sample_language is not None:
        candidates = [
            s
            for s in samples_by_id.get(sample_id, [])
            if s.get("language") == sample_language
        ]
        return random.choice(candidates) if candidates else None

    if sample_id is not None:
        candidates = samples_by_id.get(sample_id, [])
        return random.choice(candidates) if candidates else None

    if sample_language is not None:
        candidates = samples_by_language.get(sample_language, [])
        return random.choice(candidates) if candidates else None

    if random_fallback:
        return random.choice(samples) if samples else None

    return None


def build_samples_by_id(samples: list[dict]) -> dict[str, list[dict]]:
    """Group samples by their ``id`` field (multiple language variants per ID)."""
    result: dict[str, list[dict]] = {}
    for s in samples:
        result.setdefault(s["id"], []).append(s)
    return result


def build_samples_by_language(samples: list[dict]) -> dict[str, list[dict]]:
    """Group samples by their ``language`` field."""
    result: dict[str, list[dict]] = {}
    for s in samples:
        result.setdefault(s["language"], []).append(s)
    return result
