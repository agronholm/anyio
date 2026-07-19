from __future__ import annotations

import json

import anyio.abc

print(
    json.dumps(
        {
            "anyio.sleep": anyio.sleep.__module__,
            "anyio.CancelScope": anyio.CancelScope.__module__,
            "anyio.abc.CancelScope": anyio.abc.CancelScope.__module__,
            "anyio.abc.UDPSocket": anyio.abc.UDPSocket.__module__,
        }
    )
)
