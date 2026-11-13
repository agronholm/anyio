from __future__ import annotations

import asyncio
import gc
import sys
import weakref

import pytest

import anyio
from anyio.lowlevel import checkpoint


@pytest.mark.skipif(
    sys.implementation.name != "cpython",
    reason="Requires CPython reference counting",
)
@pytest.mark.parametrize("cancel_child", [False, True], ids=["returned", "cancelled"])
def test_child_released_without_cyclic_gc(cancel_child: bool) -> None:
    async def main() -> None:
        child_ref: weakref.ReferenceType[asyncio.Task[None]] | None = None

        async def child() -> None:
            nonlocal child_ref
            task = asyncio.current_task()
            assert task is not None
            child_ref = weakref.ref(task)
            del task
            if cancel_child:
                await anyio.sleep_forever()

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(child)
            await checkpoint()
            if cancel_child:
                task_group.cancel_scope.cancel()

        assert child_ref is not None
        alive_before_collection = child_ref() is not None
        gc.collect()
        assert child_ref() is None
        assert not alive_before_collection, "Child task survived until cyclic GC"

    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        anyio.run(main, backend="asyncio")
    finally:
        if gc_was_enabled:
            gc.enable()
