"""The harness. Sits ABOVE the agent runtime.

Execution Planner (does a model run at all?), Context Builder (minimal context
under a token budget), Budget Manager, result cache. Five of the planner six
paths cost nothing.

See docs/architecture/07-harness.md §2.
"""
