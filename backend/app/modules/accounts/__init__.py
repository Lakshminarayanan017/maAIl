"""Connected-account lifecycle: connect, reconnect, refresh, disconnect.

Zero-LLM zone. Nothing here may import a model client; auth is the last place
anyone should be asking a language model for an opinion.

The split is deliberate. ``states`` is the single-use nonce ledger, which runs
before anyone is authenticated and therefore holds no identity. ``service``
runs inside a tenant transaction and owns everything that belongs to a user.
"""
