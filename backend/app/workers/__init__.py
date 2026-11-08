"""Worker entrypoints: sync, intelligence, scheduled.

Every job wrapper opens a transaction and sets the tenant before touching a
user-scoped table. See app.core.tenancy.tenant_session.
"""
