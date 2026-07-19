from __future__ import annotations

import asyncio
import logging
import platform
import ssl
import sys
from collections.abc import Awaitable, Callable, Coroutine, Generator, Iterator
from ssl import SSLContext
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar
from unittest.mock import Mock

import pytest
import trustme
from _pytest.fixtures import SubRequest
from trustme import CA

from anyio import get_all_backends, get_available_backends
from anyio._core._eventloop import current_async_library

if TYPE_CHECKING:
    from blockbuster import BlockBuster

T = TypeVar("T")
P = ParamSpec("P")

uvloop_marks = []
uvloop_name = "uvloop"
try:
    if platform.system() == "Windows":
        uvloop_name = "winloop"
        import winloop as uvloop
    else:
        import uvloop
except ImportError:
    uvloop_marks.append(pytest.mark.skip(reason=f"{uvloop_name} not available"))
    uvloop = Mock()
else:
    if hasattr(asyncio.AbstractEventLoop, "shutdown_default_executor") and not hasattr(
        uvloop.loop.Loop, "shutdown_default_executor"
    ):
        uvloop_marks.append(
            pytest.mark.skip(
                reason=f"{uvloop_name} is missing shutdown_default_executor()"
            )
        )

pytest_plugins = ["pytester"]

asyncio_params = [
    pytest.param(("asyncio", {"debug": True}), id="asyncio"),
    pytest.param(
        (
            "asyncio",
            {"debug": True, "loop_factory": uvloop.new_event_loop},
        ),
        marks=uvloop_marks,
        id=f"asyncio+{uvloop_name}",
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

if platform.system() == "Windows":
    # The SelectorEventLoop can't do overlapped pipe I/O itself; exercise the fallback
    # that runs subprocess pipes on a background proactor loop
    asyncio_params.append(
        pytest.param(
            ("asyncio", {"debug": True, "loop_factory": asyncio.SelectorEventLoop}),
            id="asyncio+selector",
        ),
    )

backend_params = asyncio_params.copy()
available_backends = set(get_available_backends())
for backend_name in get_all_backends():
    if backend_name == "asyncio":
        continue

    backend_params.append(
        pytest.param(
            backend_name,
            marks=[
                pytest.mark.skipif(
                    backend_name not in available_backends,
                    reason=f"{backend_name} is not available",
                )
            ],
        )
    )


@pytest.fixture(scope="session", autouse=True)
def suppress_slow_callbacks() -> None:
    class SuppressSlowCallbacks(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return record.msg != "Executing %s took %.3f seconds"

    # Suppress the slow callback duration warning messages interfering with log capture
    # assertions on asyncio
    logging.getLogger("asyncio").addFilter(SuppressSlowCallbacks())


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


@pytest.fixture(params=backend_params)
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

    yield loop

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


@pytest.fixture
async def event_loop_implementation_name() -> str | None:
    if (name := current_async_library()) == "asyncio":
        return asyncio.get_running_loop().__module__

    return name


def return_non_coro_awaitable(
    func: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, Awaitable[T]]:
    class Wrapper:
        def __init__(self, *args: P.args, **kwargs: P.kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def __await__(self) -> Generator[Any, Any, T]:
            return func(*self.args, **self.kwargs).__await__()

    return Wrapper
