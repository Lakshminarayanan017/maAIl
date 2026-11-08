"""Proposals, binding, single-use tokens.

A proposal binds a ``content_hash`` and a ``context_version``. If either moved
between proposal and approval, the approval is stale and is refused.
"""
