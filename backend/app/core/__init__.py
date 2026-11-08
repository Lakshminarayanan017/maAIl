"""Cross-cutting concerns: settings, logging, tenancy, crypto, the clock.

Nothing in here may import from ``app.modules`` — core is the bottom of the
stack and a cycle through it would make the import-boundary tests meaningless.
"""
