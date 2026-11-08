"""Deterministic pre-pass: user rules, sender lists, the Triage bypass.

Runs before any agent. Zero-LLM zone (gap E4).
"""

from app.modules.rules.engine import RuleMatch, ThreadFacts, match_rules

__all__ = ["RuleMatch", "ThreadFacts", "match_rules"]
