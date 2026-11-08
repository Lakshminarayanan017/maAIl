"""Postgres job queue: claim with FOR UPDATE SKIP LOCKED, leases, dead-letter.

No Redis, no Celery. One datastore until a measured trigger says otherwise.
"""
