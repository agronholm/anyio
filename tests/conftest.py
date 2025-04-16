from __future__ import annotations

import asyncio
import ssl
import sys
from collections.abc import Generator, Iterator
from ssl import SSLContext
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

import pytest
import trustme
from _pytest.fixtures import SubRequest
from trustme import CA

if TYPE_CHECKING:
    from blockbuster import BlockBuster

uvloop_marks = []
try:
    import uvloop
except ImportError:
    uvloop_marks.append(pytest.mark.skip(reason="uvloop not available"))
    uvloop = Mock()
else:
    if hasattr(asyncio.AbstractEventLoop, "shutdown_default_executor") and not hasattr(
        uvloop.loop.Loop, "shutdown_default_executor"
    ):
        uvloop_marks.append(
            pytest.mark.skip(reason="uvloop is missing shutdown_default_executor()")
        )

pytest_plugins = ["pytester"]

asyncio_params = [
    pytest.param(("asyncio", {"debug": True}), id="asyncio"),
    pytest.param(
        ("asyncio", {"debug": True, "loop_factory": uvloop.new_event_loop}),
        marks=uvloop_marks,
        id="asyncio+uvloop",
    ),
]
if sys.version_info >= (3, 12):

    def eager_task_loop_factory() -> asyncio.AbstractEventLoop:
        loop = asyncio.new_event_loop()
        loop.set_task_factory(asyncio.eager_task_factory)
        return loop

    asyncio_params.append(
        pytest.param(
            ("asyncio", {"debug": True, "loop_factory": eager_task_loop_factory}),
            id="asyncio+eager",
        ),
    )


@pytest.fixture(autouse=True)
def blockbuster() -> Iterator[BlockBuster | None]:
    try:
        from blockbuster import blockbuster_ctx
    except ImportError:
        yield None
        return

    with blockbuster_ctx(
        "anyio", excluded_modules=["anyio.pytest_plugin", "anyio._backends._asyncio"]
    ) as bb:
        bb.functions["socket.socket.accept"].can_block_in(
            "anyio/_core/_asyncio_selector_thread.py", {"get_selector"}
        )
        for func in ["os.stat", "os.unlink"]:
            bb.functions[func].can_block_in(
                "anyio/_core/_sockets.py", "setup_unix_local_socket"
            )

        yield bb


@pytest.fixture
def deactivate_blockbuster(blockbuster: BlockBuster | None) -> None:
    if blockbuster is not None:
        blockbuster.deactivate()


@pytest.fixture(params=[*asyncio_params, pytest.param("trio")])
def anyio_backend(request: SubRequest) -> tuple[str, dict[str, Any]]:
    return request.param


@pytest.fixture(scope="session")
def ca() -> CA:
    return trustme.CA()


@pytest.fixture(scope="session")
def server_context(ca: CA) -> SSLContext:
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
        server_context.options &= ~ssl.OP_IGNORE_UNEXPECTED_EOF

    ca.issue_cert("localhost").configure_cert(server_context)
    return server_context


@pytest.fixture(scope="session")
def client_context(ca: CA) -> SSLContext:
    client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
        client_context.options &= ~ssl.OP_IGNORE_UNEXPECTED_EOF

    ca.configure_trust(client_context)
    return client_context


@pytest.fixture
def asyncio_event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    if sys.version_info >= (3, 13):
        loop = asyncio.EventLoop()
    else:
        loop = asyncio.new_event_loop()

    if sys.version_info < (3, 10):
        asyncio.set_event_loop(loop)

    yield loop

    if sys.version_info < (3, 10):
        asyncio.set_event_loop(None)

    loop.close()


if sys.version_info >= (3, 14):

    def no_other_refs() -> list[object]:
        return [sys._getframe(1).f_generator]

elif sys.version_info >= (3, 11):

    def no_other_refs() -> list[object]:
        return []
else:

    def no_other_refs() -> list[object]:
        return [sys._getframe(1)]
