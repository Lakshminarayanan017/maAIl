"""The agent runtime and the ten agents.

Tools reach agents only through ``app.modules.mcp``. Importing ``providers`` or
``mcp_servers`` from here is a build failure — that is the loose coupling, made
mechanical rather than aspirational.
"""
