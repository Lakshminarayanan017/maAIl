"""Two-pass Gmail sync, per-account quota limiter, bounded reconciliation.

Zero-LLM zone. Quota is per *minute* (6,000 units/user/min) and ``messages.get``
costs 20 units, or 60 with ``format=full`` — hence two passes.
"""
