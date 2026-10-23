"""Seeded, independent random streams."""

from __future__ import annotations

import hashlib
import random


def derive_rng(seed: int, stream: str) -> random.Random:
    """Return an RNG for a named stream derived from ``seed``.

    Streams are hashed (SHA-256) rather than offset so that adding a source or a
    consumer never perturbs the numbers drawn by another stream, and results
    do not depend on the Python version's seeding of string/tuple seeds.
    """
    digest = hashlib.sha256(f"{seed}:{stream}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))
