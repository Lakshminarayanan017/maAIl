"""PLANE X. Executes an approved proposal.

**No model. Ever.** No LLM client may be imported anywhere under this package;
``tests/arch/test_import_boundaries.py`` fails the build if one is.

Re-validates the allowlist, the grant, the content hash, the context version
and the single-use token, then acts idempotently and writes an audit row.
"""
