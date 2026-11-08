"""Tier 0 — parse, HTML to text, strip quotes, normalise, date candidates.

**Plane U data, zero models.** Everything here is deterministic code, and the
quote stripper is the largest single cost lever in the system (60-80% token
reduction before a model ever sees a thread).

Zero-LLM zone. See docs/architecture/07-harness.md §6.
"""
