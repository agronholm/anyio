from __future__ import annotations

# Re-exported here, for backwards compatibility
# isort: off

# Re-export imports so they look like they live directly in this package
for value in list(locals().copy().values()):
    if getattr(value, "__module__", "").startswith("anyio.abc."):
        value.__module__ = __name__
