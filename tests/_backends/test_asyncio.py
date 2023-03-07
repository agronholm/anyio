from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from _pytest.fixtures import getfixturemarker

from anyio import create_task_group
from anyio._backends._asyncio import cancelling
from anyio.abc import TaskStatus
from anyio.lowlevel import cancel_shielded_checkpoint, checkpoint
from anyio.pytest_plugin import anyio_backend_name

try:
    from .conftest import anyio_backend as parent_anyio_backend
except ImportError:
    from ..conftest import anyio_backend as parent_anyio_backend

pytestmark = pytest.mark.anyio

# Use the inherited anyio_backend, but filter out non-asyncio
anyio_backend = pytest.fixture(
    params=[
        param
        for param in cast(Any, getfixturemarker(parent_anyio_backend)).params
        if any(
            "asyncio"
            in anyio_backend_name.__wrapped__(backend)  # type: ignore[attr-defined]
            for backend in param.values
        )
    ]
)(parent_anyio_backend.__wrapped__)


async def test_cancelling() -> None:
    async def func(*, task_status: TaskStatus[asyncio.Task]) -> None:
        task = cast(asyncio.Task, asyncio.current_task())
        task_status.started(task)
        try:
            await checkpoint()
        finally:
            await cancel_shielded_checkpoint()

    async with create_task_group() as tg:
        task = cast(asyncio.Task, await tg.start(func))
        assert not cancelling(task)
        tg.cancel_scope.cancel()
        assert cancelling(task)
