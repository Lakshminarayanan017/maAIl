"""Four memory types, two stores.

working     assembled per run, never persisted
episodic    a retrieval VIEW over existing tables, not a parallel store
semantic    ``semantic_facts``, written only from validated Plane C proposals
procedural  Git, read at deploy, never written at runtime

Semantic memory is a *persistent* injection target. See 05-memory.md §2.
"""
