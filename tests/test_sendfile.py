from __future__ import annotations

import asyncio
import errno
import os
import socket
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from anyio import (
    BrokenResourceError,
    BusyResourceError,
    CancelScope,
    ClosedResourceError,
    connect_tcp,
    create_task_group,
    wait_all_tasks_blocked,
)
from anyio.abc import SocketAttribute, SocketStream, UNIXSocketStream


@pytest.fixture(autouse=True)
def remove_payload(tmp_path: Path) -> Iterator[None]:
    yield
    (tmp_path / "payload").unlink(missing_ok=True)


@pytest.fixture(params=["tcp", "unix"])
async def streams(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[SocketStream, SocketStream]]:
    if request.param == "tcp":
        # TCP works with native sendfile on macOS as well as Linux.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            receiver = await connect_tcp(*listener.getsockname())
            server, _ = listener.accept()

        server.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sender = await SocketStream.from_socket(server)
    else:
        if not hasattr(socket, "AF_UNIX"):
            pytest.skip("UNIX sockets unavailable")

        server, client = socket.socketpair(socket.AF_UNIX)
        server.setblocking(False)
        client.setblocking(False)
        sender = await UNIXSocketStream.from_socket(server)
        receiver = await UNIXSocketStream.from_socket(client)

    server.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    async with sender, receiver:
        yield sender, receiver


@pytest.fixture(params=[False, True], ids=["native", "fallback"])
async def copying(
    request: pytest.FixtureRequest,
    monkeypatch: MonkeyPatch,
    anyio_backend_name: str,
    streams: tuple[SocketStream, SocketStream],
) -> bool:
    copying = bool(request.param)
    if copying:
        if anyio_backend_name == "asyncio" and not isinstance(
            streams[0], UNIXSocketStream
        ):

            async def unavailable(*args: object, **kwargs: object) -> int:
                raise NotImplementedError

            monkeypatch.setattr(asyncio.get_running_loop(), "sendfile", unavailable)
        else:

            def unavailable_native(*args: object) -> int:
                raise OSError(errno.ENOSYS, "sendfile unavailable")

            monkeypatch.setattr(os, "sendfile", unavailable_native, raising=False)

    return copying


async def test_backpressure_and_ordering(
    streams: tuple[SocketStream, SocketStream], tmp_path: Path, copying: bool
) -> None:
    sender, receiver = streams
    payload = bytes(range(256)) * 16_384
    path = tmp_path / "payload"
    path.write_bytes(payload)
    prefix = b"headers\r\n\r\n"
    suffix = b"trailer"
    expected = prefix + payload[17:-23] + suffix
    received = bytearray()
    done = False

    with path.open("rb") as file:

        async def transmit() -> None:
            nonlocal done
            await sender.send(prefix)
            assert (
                await sender.sendfile(file, 17, len(payload) - 40) == len(payload) - 40
            )
            assert file.tell() == len(payload) - 23
            await sender.send(suffix)
            done = True

        async with create_task_group() as tg:
            tg.start_soon(transmit)
            await wait_all_tasks_blocked()
            assert not done
            if os.name == "posix":
                assert not os.get_blocking(
                    sender.extra(SocketAttribute.raw_socket).fileno()
                )
            with pytest.raises(BusyResourceError):
                await sender.send(b"interleaved")

            with pytest.raises(BusyResourceError):
                await sender.sendfile(file)

            # A blocked sendfile must not prevent simultaneous reads on this socket.
            await receiver.send(b"ping")
            assert await sender.receive() == b"ping"
            while len(received) < len(expected):
                received.extend(await receiver.receive())

    assert received == expected


async def test_cancel_blocked_transfer(
    streams: tuple[SocketStream, SocketStream], tmp_path: Path, copying: bool
) -> None:
    sender, _ = streams
    path = tmp_path / "payload"
    path.write_bytes(b"x" * 4_000_000)
    scope = CancelScope()
    with path.open("rb") as file:
        file.seek(13)

        async def transmit() -> None:
            with scope:
                await sender.sendfile(file, 13)
                pytest.fail("transfer completed without a reader")

        async with create_task_group() as tg:
            tg.start_soon(transmit)
            await wait_all_tasks_blocked()
            scope.cancel()

        assert scope.cancelled_caught
        assert 13 <= file.tell() < path.stat().st_size
        if os.name == "posix":
            assert not os.get_blocking(
                sender.extra(SocketAttribute.raw_socket).fileno()
            )


async def test_close_blocked_transfer(
    streams: tuple[SocketStream, SocketStream], tmp_path: Path, copying: bool
) -> None:
    sender, _ = streams
    path = tmp_path / "payload"
    path.write_bytes(b"x" * 4_000_000)
    with path.open("rb") as file:

        async def transmit() -> None:
            with pytest.raises((ClosedResourceError, BrokenResourceError)):
                await sender.sendfile(file)

        async with create_task_group() as tg:
            tg.start_soon(transmit)
            await wait_all_tasks_blocked()
            await sender.aclose()


async def test_closed_stream(
    streams: tuple[SocketStream, SocketStream], tmp_path: Path
) -> None:
    sender, _ = streams
    path = tmp_path / "payload"
    path.write_bytes(b"x")
    await sender.aclose()
    with path.open("rb") as file:
        with pytest.raises(ClosedResourceError):
            await sender.sendfile(file)
