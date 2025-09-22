from __future__ import annotations

import array
import errno
import gc
import io
import os
import platform
import re
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Generator, Iterable, Iterator
from contextlib import suppress
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from socket import AddressFamily
from ssl import SSLContext, SSLError
from threading import Thread
from typing import TYPE_CHECKING, Any, Literal, NoReturn, Protocol, TypeVar, cast
from unittest import mock
from unittest.mock import MagicMock, patch

import psutil
import pytest
from _pytest.fixtures import SubRequest
from _pytest.logging import LogCaptureFixture
from _pytest.monkeypatch import MonkeyPatch
from _pytest.tmpdir import TempPathFactory
from pytest import FixtureRequest
from pytest_mock.plugin import MockerFixture

from anyio import (
    BrokenResourceError,
    BusyResourceError,
    ClosedResourceError,
    EndOfStream,
    Event,
    TCPConnectable,
    TypedAttributeLookupError,
    UNIXConnectable,
    as_connectable,
    connect_tcp,
    connect_unix,
    create_connected_udp_socket,
    create_connected_unix_datagram_socket,
    create_task_group,
    create_tcp_listener,
    create_udp_socket,
    create_unix_datagram_socket,
    create_unix_listener,
    fail_after,
    getaddrinfo,
    getnameinfo,
    move_on_after,
    notify_closing,
    wait_all_tasks_blocked,
    wait_readable,
    wait_socket_readable,
    wait_socket_writable,
    wait_writable,
)
from anyio._core._eventloop import get_async_backend
from anyio.abc import (
    ConnectedUDPSocket,
    ConnectedUNIXDatagramSocket,
    IPSockAddrType,
    Listener,
    SocketAttribute,
    SocketListener,
    SocketStream,
    UDPSocket,
    UNIXDatagramSocket,
    UNIXSocketStream,
)
from anyio.lowlevel import checkpoint
from anyio.streams.stapled import MultiListener
from anyio.streams.tls import TLSConnectable

from .conftest import asyncio_params, no_other_refs

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

if TYPE_CHECKING:
    from _typeshed import FileDescriptorLike

AnyIPAddressFamily = Literal[
    AddressFamily.AF_UNSPEC, AddressFamily.AF_INET, AddressFamily.AF_INET6
]

# If a socket can bind to ::1, the current environment has IPv6 properly configured
has_ipv6 = False
if socket.has_ipv6:
    try:
        s = socket.socket(AddressFamily.AF_INET6)
        try:
            s.bind(("::1", 0))
        finally:
            s.close()
            del s
    except OSError:
        pass
    else:
        has_ipv6 = True

skip_ipv6_mark = pytest.mark.skipif(not has_ipv6, reason="IPv6 is not available")
skip_unix_abstract_mark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Abstract namespace sockets is a Linux only feature",
)


@pytest.fixture
def fake_localhost_dns(monkeypatch: MonkeyPatch) -> None:
    def fake_getaddrinfo(*args: Any, **kwargs: Any) -> object:
        # Make it return IPv4 addresses first so we can test the IPv6 preference
        results = real_getaddrinfo(*args, **kwargs)
        return sorted(results, key=lambda item: item[0])

    real_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)


@pytest.fixture(
    params=[
        pytest.param(AddressFamily.AF_INET, id="ipv4"),
        pytest.param(AddressFamily.AF_INET6, id="ipv6", marks=[skip_ipv6_mark]),
    ]
)
def family(request: SubRequest) -> AnyIPAddressFamily:
    return request.param


@pytest.fixture
def check_asyncio_bug(anyio_backend_name: str, family: AnyIPAddressFamily) -> None:
    if (
        anyio_backend_name == "asyncio"
        and sys.platform == "win32"
        and family == AddressFamily.AF_INET6
    ):
        import asyncio

        policy = asyncio.get_event_loop_policy()
        if policy.__class__.__name__ == "WindowsProactorEventLoopPolicy":
            pytest.skip("Does not work due to a known bug (39148)")


class SockFdFactoryProtocol(Protocol):
    def __call__(
        self,
        family: socket.AddressFamily,
        kind: socket.SocketKind,
        *,
        bound: bool = False,
        connected: bool = False,
    ) -> socket.socket | int: ...


@pytest.fixture(
    params=[pytest.param(False, id="sock"), pytest.param(True, id="fileno")]
)
def sock_or_fd_factory(
    request: SubRequest, tmp_path_factory: TempPathFactory
) -> SockFdFactoryProtocol:
    def factory(
        family: socket.AddressFamily,
        kind: socket.SocketKind,
        *,
        bound: bool = False,
        connected: bool = False,
    ) -> socket.socket | int:
        sock = socket.socket(family, kind)

        if bound or connected:
            if family in (socket.AF_INET, socket.AF_INET6):
                local_addr: str | tuple[str, int] = ("localhost", 0)
            else:
                local_addr = str(tmp_path_factory.mktemp("anyio") / "socket")

        if bound:
            sock.bind(local_addr)
            if kind == socket.SOCK_STREAM:
                sock.listen()
        elif connected:
            server_sock = socket.socket(family, kind)
            request.addfinalizer(server_sock.close)
            server_sock.bind(local_addr)
            if kind == socket.SOCK_STREAM:
                server_sock.listen()

            sock.connect(server_sock.getsockname())

        if request.param:
            return sock.detach()
        else:
            request.addfinalizer(sock.close)
            return sock

    return factory


_T = TypeVar("_T")


def _identity(v: _T) -> _T:
    return v


def fill_socket(sock: socket.socket) -> None:
    try:
        while True:
            sock.send(b"x" * 65536)
    except BlockingIOError:
        pass


#  _ProactorBasePipeTransport.abort() after _ProactorBasePipeTransport.close()
# does not cancel writes: https://bugs.python.org/issue44428
_ignore_win32_resource_warnings = (
    pytest.mark.filterwarnings(
        "ignore:unclosed <socket.socket:ResourceWarning",
        "ignore:unclosed transport <_ProactorSocketTransport closing:ResourceWarning",
    )
    if sys.version_info < (3, 10) and sys.platform == "win32"
    else _identity
)


@_ignore_win32_resource_warnings
class TestTCPStream:
    @pytest.fixture
    def server_sock(self, family: AnyIPAddressFamily) -> Iterator[socket.socket]:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(1)
        sock.bind(("localhost", 0))
        sock.listen()
        yield sock
        sock.close()

    @pytest.fixture
    def server_addr(self, server_sock: socket.socket) -> tuple[str, int]:
        return server_sock.getsockname()[:2]

    async def test_extra_attributes(
        self,
        server_sock: socket.socket,
        server_addr: tuple[str, int],
        family: AnyIPAddressFamily,
    ) -> None:
        async with await connect_tcp(*server_addr) as stream:
            raw_socket = stream.extra(SocketAttribute.raw_socket)
            assert stream.extra(SocketAttribute.family) == family
            assert (
                stream.extra(SocketAttribute.local_address)
                == raw_socket.getsockname()[:2]
            )
            assert (
                stream.extra(SocketAttribute.local_port) == raw_socket.getsockname()[1]
            )
            assert stream.extra(SocketAttribute.remote_address) == server_addr
            assert stream.extra(SocketAttribute.remote_port) == server_addr[1]

    async def test_send_receive(
        self, server_sock: socket.socket, server_addr: tuple[str, int]
    ) -> None:
        async with await connect_tcp(*server_addr) as stream:
            client, _ = server_sock.accept()
            await stream.send(b"blah")
            request = client.recv(100)
            client.sendall(request[::-1])
            response = await stream.receive()
            client.close()

        assert response == b"halb"

    async def test_send_large_buffer(
        self, server_sock: socket.socket, server_addr: tuple[str, int]
    ) -> None:
        def serve() -> None:
            client, _ = server_sock.accept()
            client.sendall(buffer)
            client.close()

        buffer = (
            b"\xff" * 1024 * 1024
        )  # should exceed the maximum kernel send buffer size
        async with await connect_tcp(*server_addr) as stream:
            thread = Thread(target=serve, daemon=True)
            thread.start()
            response = b""
            while len(response) < len(buffer):
                chunk = await stream.receive()
                assert isinstance(chunk, bytes)
                response += chunk

        thread.join()
        assert response == buffer

    async def test_send_eof(
        self, server_sock: socket.socket, server_addr: tuple[str, int]
    ) -> None:
        def serve() -> None:
            client, _ = server_sock.accept()
            request = b""
            while True:
                data = client.recv(100)
                request += data
                if not data:
                    break

            client.sendall(request[::-1])
            client.close()

        async with await connect_tcp(*server_addr) as stream:
            thread = Thread(target=serve, daemon=True)
            thread.start()
            await stream.send(b"hello, ")
            await stream.send(b"world\n")
            await stream.send_eof()
            response = await stream.receive()

        thread.join()
        assert response == b"\ndlrow ,olleh"

    async def test_iterate(
        self, server_sock: socket.socket, server_addr: tuple[str, int]
    ) -> None:
        def serve() -> None:
            client, _ = server_sock.accept()
            client.sendall(b"bl")
            event.wait(1)
            client.sendall(b"ah")
            client.close()

        event = threading.Event()
        thread = Thread(target=serve, daemon=True)
        thread.start()
        chunks = []
        async with await connect_tcp(*server_addr) as stream:
            async for chunk in stream:
                chunks.append(chunk)
                event.set()

        thread.join()
        assert chunks == [b"bl", b"ah"]

    async def test_socket_options(
        self, family: AnyIPAddressFamily, server_addr: tuple[str, int]
    ) -> None:
        async with await connect_tcp(*server_addr) as stream:
            raw_socket = stream.extra(SocketAttribute.raw_socket)
            assert raw_socket.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0

    @skip_ipv6_mark
    @pytest.mark.parametrize(
        "local_addr, expected_client_addr",
        [
            pytest.param("", "::1", id="dualstack"),
            pytest.param("127.0.0.1", "127.0.0.1", id="ipv4"),
            pytest.param("::1", "::1", id="ipv6"),
        ],
    )
    async def test_happy_eyeballs(
        self, local_addr: str, expected_client_addr: str, fake_localhost_dns: None
    ) -> None:
        client_addr = None, None

        def serve() -> None:
            nonlocal client_addr
            client, client_addr = server_sock.accept()
            client.close()

        family = (
            AddressFamily.AF_INET
            if local_addr == "127.0.0.1"
            else AddressFamily.AF_INET6
        )
        server_sock = socket.socket(family)
        server_sock.bind((local_addr, 0))
        server_sock.listen()
        port = server_sock.getsockname()[1]
        thread = Thread(target=serve, daemon=True)
        thread.start()

        async with await connect_tcp("localhost", port):
            pass

        thread.join()
        server_sock.close()
        assert client_addr[0] == expected_client_addr

    @pytest.mark.skipif(
        sys.implementation.name == "pypy",
        reason=(
            "gc.get_referrers is broken on PyPy (see "
            "https://github.com/pypy/pypy/issues/5075)"
        ),
    )
    async def test_happy_eyeballs_refcycles(
        self, free_tcp_port: int, anyio_backend_name: str
    ) -> None:
        """
        Test derived from https://github.com/python/cpython/pull/124859
        """
        if anyio_backend_name == "asyncio" and sys.version_info < (3, 10):
            pytest.skip(
                "asyncio.BaseEventLoop.create_connection creates refcycles on py 3.9"
            )

        exc = None
        try:
            async with await connect_tcp("127.0.0.1", free_tcp_port):
                pass
        except OSError as e:
            exc = e.__cause__

        assert isinstance(exc, OSError)
        assert gc.get_referrers(exc) == no_other_refs()

    @pytest.mark.parametrize(
        "target, exception_class",
        [
            pytest.param(
                "localhost", ExceptionGroup, id="multi", marks=[skip_ipv6_mark]
            ),
            pytest.param("127.0.0.1", ConnectionRefusedError, id="single"),
        ],
    )
    async def test_connection_refused(
        self,
        target: str,
        exception_class: type[ExceptionGroup] | type[ConnectionRefusedError],
        fake_localhost_dns: None,
        free_tcp_port: int,
    ) -> None:
        with pytest.raises(OSError) as exc:
            await connect_tcp(target, free_tcp_port)

        assert exc.match("All connection attempts failed")
        assert isinstance(exc.value.__cause__, exception_class)
        if isinstance(exc.value.__cause__, ExceptionGroup):
            for exception in exc.value.__cause__.exceptions:
                assert isinstance(exception, ConnectionRefusedError)

    async def test_receive_timeout(
        self, server_sock: socket.socket, server_addr: tuple[str, int]
    ) -> None:
        def serve() -> None:
            conn, _ = server_sock.accept()
            time.sleep(1)
            conn.close()

        thread = Thread(target=serve, daemon=True)
        thread.start()
        async with await connect_tcp(*server_addr) as stream:
            start_time = time.monotonic()
            with move_on_after(0.1):
                while time.monotonic() - start_time < 0.3:
                    await stream.receive(1)

                pytest.fail("The timeout was not respected")

    async def test_concurrent_send(self, server_addr: tuple[str, int]) -> None:
        async def send_data() -> NoReturn:
            while True:
                await stream.send(b"\x00" * 4096)

        async with await connect_tcp(*server_addr) as stream:
            async with create_task_group() as tg:
                tg.start_soon(send_data)
                await wait_all_tasks_blocked()
                with pytest.raises(BusyResourceError) as exc:
                    await stream.send(b"foo")

                exc.match("already writing to")
                tg.cancel_scope.cancel()

    async def test_concurrent_receive(self, server_addr: tuple[str, int]) -> None:
        async with await connect_tcp(*server_addr) as client:
            async with create_task_group() as tg:
                tg.start_soon(client.receive)
                await wait_all_tasks_blocked()
                try:
                    with pytest.raises(BusyResourceError) as exc:
                        await client.receive()

                    exc.match("already reading from")
                finally:
                    tg.cancel_scope.cancel()

    async def test_close_during_receive(self, server_addr: tuple[str, int]) -> None:
        async def interrupt() -> None:
            await wait_all_tasks_blocked()
            await stream.aclose()

        async with await connect_tcp(*server_addr) as stream:
            async with create_task_group() as tg:
                tg.start_soon(interrupt)
                with pytest.raises(ClosedResourceError):
                    await stream.receive()

    async def test_receive_after_close(self, server_addr: tuple[str, int]) -> None:
        stream = await connect_tcp(*server_addr)
        await stream.aclose()
        with pytest.raises(ClosedResourceError):
            await stream.receive()

    async def test_send_after_close(self, server_addr: tuple[str, int]) -> None:
        stream = await connect_tcp(*server_addr)
        await stream.aclose()
        with pytest.raises(ClosedResourceError):
            await stream.send(b"foo")

    async def test_receive_after_peer_closed(
        self, family: AnyIPAddressFamily, request: FixtureRequest
    ) -> None:
        server_sock = socket.create_server(("localhost", 0), family=family)
        request.addfinalizer(server_sock.close)
        server_sock.settimeout(1)
        server_addr = server_sock.getsockname()[:2]

        async with await connect_tcp(*server_addr) as stream:
            client_sock, _ = server_sock.accept()
            client_sock.close()
            with pytest.raises(EndOfStream):
                await stream.receive(1)

        with pytest.raises(ClosedResourceError):
            await stream.receive(1)

    async def test_send_after_peer_closed(
        self, family: AnyIPAddressFamily, request: FixtureRequest
    ) -> None:
        server_sock = socket.create_server(("localhost", 0), family=family)
        request.addfinalizer(server_sock.close)
        server_sock.settimeout(1)
        server_addr = server_sock.getsockname()[:2]

        async with await connect_tcp(*server_addr) as stream:
            client_sock, _ = server_sock.accept()
            client_sock.close()
            with pytest.raises(BrokenResourceError):
                for _ in range(1000):
                    await stream.send(b"foo")

        with pytest.raises(ClosedResourceError):
            await stream.send(b"foo")

    async def test_connect_tcp_with_tls(
        self,
        server_context: SSLContext,
        client_context: SSLContext,
        server_sock: socket.socket,
        server_addr: tuple[str, int],
    ) -> None:
        def serve() -> None:
            with suppress(socket.timeout):
                client, addr = server_sock.accept()
                client.settimeout(1)
                client = server_context.wrap_socket(client, server_side=True)
                data = client.recv(100)
                client.sendall(data[::-1])
                client.unwrap()
                client.close()

        # The TLSStream tests are more comprehensive than this one!
        thread = Thread(target=serve, daemon=True)
        thread.start()
        async with await connect_tcp(
            *server_addr, tls_hostname="localhost", ssl_context=client_context
        ) as stream:
            await stream.send(b"hello")
            response = await stream.receive()

        assert response == b"olleh"
        thread.join()

    async def test_connect_tcp_with_tls_cert_check_fail(
        self,
        server_context: SSLContext,
        server_sock: socket.socket,
        server_addr: tuple[str, int],
    ) -> None:
        thread_exception = None

        def serve() -> None:
            nonlocal thread_exception
            client, addr = server_sock.accept()
            with client:
                client.settimeout(1)
                try:
                    server_context.wrap_socket(client, server_side=True)
                except OSError:
                    pass
                except BaseException as exc:
                    thread_exception = exc

        thread = Thread(target=serve, daemon=True)
        thread.start()
        with pytest.raises(SSLError):
            await connect_tcp(*server_addr, tls_hostname="localhost")

        thread.join()
        assert thread_exception is None

    @pytest.mark.parametrize("anyio_backend", asyncio_params)
    async def test_unretrieved_future_exception_server_crash(
        self, family: AnyIPAddressFamily, caplog: LogCaptureFixture
    ) -> None:
        """
        Test that there won't be any leftover Futures that don't get their exceptions
        retrieved.

        See https://github.com/encode/httpcore/issues/382 for details.
        """

        def serve() -> None:
            sock, addr = server_sock.accept()
            event.wait(3)
            sock.close()
            del sock
            gc.collect()

        with socket.socket(family, socket.SOCK_STREAM) as server_sock:
            server_sock.settimeout(1)
            server_sock.bind(("localhost", 0))
            server_sock.listen()
            server_addr = server_sock.getsockname()[:2]
            event = threading.Event()
            thread = Thread(target=serve)
            thread.start()
            async with await connect_tcp(*server_addr) as stream:
                await stream.send(b"GET")
                event.set()
                with pytest.raises(BrokenResourceError):
                    await stream.receive()

            thread.join()
            gc.collect()
            caplog_text = "\n".join(
                msg
                for msg in caplog.messages
                if not re.search("took [0-9.]+ seconds", msg)
            )
            assert not caplog_text

    async def test_from_socket(
        self, family: AnyIPAddressFamily, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(family, socket.SOCK_STREAM, connected=True)
        async with await SocketStream.from_socket(sock_or_fd) as stream:
            assert isinstance(stream, SocketStream)
            assert stream.extra(SocketAttribute.family) == family

    async def test_from_socket_not_a_socket(self) -> None:
        with pytest.raises(
            TypeError,
            match="expected an int or socket, got str instead",
        ):
            await SocketStream.from_socket("foo")  # type: ignore[arg-type]

    async def test_from_socket_pass_file_fd(self, tmp_path: Path) -> None:
        with pytest.raises(
            ValueError,
            match="the file descriptor does not refer to a socket",
        ):
            with tmp_path.joinpath("foo").open("wb") as fd:
                await SocketStream.from_socket(fd.fileno())

    async def test_from_socket_wrong_socket_type(
        self, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(
            socket.AF_INET, socket.SocketKind.SOCK_DGRAM, connected=True
        )
        with pytest.raises(
            ValueError,
            match="socket type mismatch: expected SOCK_STREAM, got SOCK_DGRAM",
        ):
            await SocketStream.from_socket(sock_or_fd)

    async def test_from_socket_not_connected(
        self, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(socket.AF_INET, socket.SOCK_STREAM, bound=True)
        with pytest.raises(ValueError, match="the socket must be connected"):
            await SocketStream.from_socket(sock_or_fd)


@pytest.mark.network
class TestTCPListener:
    async def test_extra_attributes(self, family: AnyIPAddressFamily) -> None:
        async with await create_tcp_listener(
            local_host="localhost", family=family
        ) as multi:
            assert multi.extra(SocketAttribute.family) == family
            for listener in multi.listeners:
                raw_socket = listener.extra(SocketAttribute.raw_socket)
                assert listener.extra(SocketAttribute.family) == family
                assert (
                    listener.extra(SocketAttribute.local_address)
                    == raw_socket.getsockname()[:2]
                )
                assert (
                    listener.extra(SocketAttribute.local_port)
                    == raw_socket.getsockname()[1]
                )
                pytest.raises(
                    TypedAttributeLookupError,
                    listener.extra,
                    SocketAttribute.remote_address,
                )
                pytest.raises(
                    TypedAttributeLookupError,
                    listener.extra,
                    SocketAttribute.remote_port,
                )

    @pytest.mark.parametrize(
        "family",
        [
            pytest.param(AddressFamily.AF_INET, id="ipv4"),
            pytest.param(AddressFamily.AF_INET6, id="ipv6", marks=[skip_ipv6_mark]),
            pytest.param(socket.AF_UNSPEC, id="both", marks=[skip_ipv6_mark]),
        ],
    )
    async def test_accept(self, family: AnyIPAddressFamily) -> None:
        async with await create_tcp_listener(
            local_host="localhost", family=family
        ) as multi:
            for listener in multi.listeners:
                client = socket.socket(listener.extra(SocketAttribute.family))
                client.settimeout(1)
                addr = listener.extra(SocketAttribute.local_address)
                host, port = addr[0], addr[1]

                # On Windows, connecting to ANY (:: or 0.0.0.0) is invalid (WinError 10049).
                # Replace it with loopback (::1 or 127.0.0.1) to make the test portable.
                if sys.platform == "win32" and host in ("::", "0.0.0.0"):
                    family = listener.extra(SocketAttribute.family)
                    if family == socket.AF_INET6:
                        addr = ("::1", port)
                    elif family == socket.AF_INET:
                        addr = ("127.0.0.1", port)

                client.connect(addr)

                assert isinstance(listener, SocketListener)
                stream = await listener.accept()
                client.sendall(b"blah")
                request = await stream.receive()
                await stream.send(request[::-1])
                assert client.recv(100) == b"halb"
                client.close()
                await stream.aclose()

    async def test_accept_after_close(self, family: AnyIPAddressFamily) -> None:
        async with await create_tcp_listener(
            local_host="localhost", family=family
        ) as multi:
            for listener in multi.listeners:
                await listener.aclose()
                assert isinstance(listener, SocketListener)
                with pytest.raises(ClosedResourceError):
                    await listener.accept()

    async def test_socket_options(self, family: AnyIPAddressFamily) -> None:
        async with await create_tcp_listener(
            local_host="localhost", family=family
        ) as multi:
            for listener in multi.listeners:
                raw_socket = listener.extra(SocketAttribute.raw_socket)
                if sys.platform == "win32":
                    assert (
                        raw_socket.getsockopt(
                            socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE
                        )
                        != 0
                    )
                else:
                    assert (
                        raw_socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR)
                        != 0
                    )

                raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 80000)
                assert raw_socket.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) in (
                    80000,
                    160000,
                )

                client = socket.socket(raw_socket.family)
                client.settimeout(1)
                client.connect(raw_socket.getsockname())

                assert isinstance(listener, SocketListener)
                async with await listener.accept() as stream:
                    raw_socket = stream.extra(SocketAttribute.raw_socket)
                    assert raw_socket.gettimeout() == 0
                    assert raw_socket.family == listener.extra(SocketAttribute.family)
                    assert (
                        raw_socket.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
                        != 0
                    )

                client.close()

    @pytest.mark.skipif(
        not hasattr(socket, "SO_REUSEPORT"), reason="SO_REUSEPORT option not supported"
    )
    async def test_reuse_port(self, family: AnyIPAddressFamily) -> None:
        multi1 = await create_tcp_listener(
            local_host="localhost", family=family, reuse_port=True
        )
        assert len(multi1.listeners) == 1

        multi2 = await create_tcp_listener(
            local_host="localhost",
            local_port=multi1.listeners[0].extra(SocketAttribute.local_port),
            family=family,
            reuse_port=True,
        )
        assert len(multi2.listeners) == 1

        assert multi1.listeners[0].extra(
            SocketAttribute.local_address
        ) == multi2.listeners[0].extra(SocketAttribute.local_address)
        await multi1.aclose()
        await multi2.aclose()

    async def test_close_from_other_task(self, family: AnyIPAddressFamily) -> None:
        listener = await create_tcp_listener(local_host="localhost", family=family)
        with pytest.raises(ExceptionGroup) as exc:
            async with create_task_group() as tg:
                tg.start_soon(listener.serve, lambda stream: None)
                await wait_all_tasks_blocked()
                await listener.aclose()
                tg.cancel_scope.cancel()

        assert len(exc.value.exceptions) == 1
        assert isinstance(exc.value.exceptions[0], ExceptionGroup)
        nested_grp = exc.value.exceptions[0]
        assert len(nested_grp.exceptions) == 1
        assert isinstance(nested_grp.exceptions[0], ExceptionGroup)

    async def test_send_after_eof(self, family: AnyIPAddressFamily) -> None:
        async def handle(stream: SocketStream) -> None:
            async with stream:
                await stream.send(b"Hello\n")

        multi = await create_tcp_listener(family=family, local_host="localhost")
        async with multi, create_task_group() as tg:
            tg.start_soon(multi.serve, handle)
            await wait_all_tasks_blocked()

            with socket.socket(family) as client:
                client.connect(multi.extra(SocketAttribute.local_address))
                client.shutdown(socket.SHUT_WR)
                client.setblocking(False)
                with fail_after(1):
                    while True:
                        try:
                            message = client.recv(10)
                        except BlockingIOError:
                            await checkpoint()
                        else:
                            assert message == b"Hello\n"
                            break

            tg.cancel_scope.cancel()

    async def test_eof_after_send(self, family: AnyIPAddressFamily) -> None:
        """Regression test for #701."""
        received_bytes = b""

        async def handle(stream: SocketStream) -> None:
            nonlocal received_bytes
            async with stream:
                received_bytes = await stream.receive()
                with pytest.raises(EndOfStream), fail_after(1):
                    await stream.receive()

            tg.cancel_scope.cancel()

        multi = await create_tcp_listener(family=family, local_host="localhost")
        async with multi, create_task_group() as tg:
            with socket.socket(family) as client:
                client.connect(multi.extra(SocketAttribute.local_address))
                client.send(b"Hello")
                client.shutdown(socket.SHUT_WR)
                await multi.serve(handle)

        assert received_bytes == b"Hello"

    @skip_ipv6_mark
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Windows does not support interface name suffixes",
    )
    async def test_bind_link_local(self) -> None:
        # Regression test for #554
        link_local_ipv6_address = next(
            (
                addr.address
                for addresses in psutil.net_if_addrs().values()
                for addr in addresses
                if addr.address.startswith("fe80::") and "%" in addr.address
            ),
            None,
        )
        if link_local_ipv6_address is None:
            pytest.fail("Could not find a link-local IPv6 interface")

        async with await create_tcp_listener(local_host=link_local_ipv6_address):
            pass

    async def test_from_socket(
        self, family: AnyIPAddressFamily, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(family, socket.SOCK_STREAM, bound=True)
        async with await SocketListener.from_socket(sock_or_fd) as listener:
            assert isinstance(listener, SocketListener)
            assert listener.extra(SocketAttribute.family) == family

    async def test_from_socket_not_bound(
        self, family: AnyIPAddressFamily, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(family, socket.SOCK_STREAM)
        with pytest.raises(ValueError, match="the socket must be bound"):
            await SocketListener.from_socket(sock_or_fd)

    @pytest.mark.parametrize(
        "local_host,family,expected_listeners,local_port",
        [
            (None, AddressFamily.AF_UNSPEC, 1 if socket.has_dualstack_ipv6() else 2, 0),
            ("localhost", AddressFamily.AF_UNSPEC, 2, 0),
            ("localhost", AddressFamily.AF_INET, 1, 0),
            ("::", AddressFamily.AF_UNSPEC, 1, 0),
            ("127.0.0.1", AddressFamily.AF_INET, 1, 0),
            ("::1", AddressFamily.AF_INET6, 1, 0),
            (
                None,
                AddressFamily.AF_UNSPEC,
                1 if socket.has_dualstack_ipv6() else 2,
                54321,
            ),
            ("localhost", AddressFamily.AF_UNSPEC, 2, 54321),
            ("localhost", AddressFamily.AF_INET, 1, 54321),
        ],
    )
    async def test_tcp_listener_same_port(
        self,
        local_host: str | None,
        family: AnyIPAddressFamily,
        expected_listeners: int,
        local_port: int,
    ) -> None:
        async with await create_tcp_listener(
            local_host=local_host, family=family, local_port=local_port
        ) as multi:
            ports = {
                listener.extra(SocketAttribute.local_port)
                for listener in multi.listeners
            }
            assert len(ports) == 1
            if local_port != 0:
                assert ports == {local_port}

            assert len(multi.listeners) == expected_listeners

    @skip_ipv6_mark
    async def test_tcp_listener_dualstack_disabled(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        monkeypatch.setattr(socket, "has_dualstack_ipv6", lambda: False)

        async with await create_tcp_listener(
            local_host=None, family=AddressFamily.AF_UNSPEC
        ) as multi:
            families = {
                listener.extra(SocketAttribute.family) for listener in multi.listeners
            }
            assert families == {socket.AF_INET, socket.AF_INET6}
            assert len(multi.listeners) == 2

            ports = {
                listener.extra(SocketAttribute.local_port)
                for listener in multi.listeners
            }
            assert len(ports) == 1

    async def test_tcp_listener_retry_after_partial_failure(self) -> None:
        """
        Simulate a case where the first bind() succeeds with an ephemeral port,
        the second bind() fails with EADDRINUSE, and verify that create_tcp_listener
        retries and eventually succeeds with all listeners bound to the same port.
        """

        real_bind = socket.socket.bind
        bind_count = 0
        fail_once = True

        def fake_bind(
            self: socket.socket, addr: tuple[str, int] | tuple[str, int, int, int]
        ) -> None:
            nonlocal bind_count, fail_once
            port = addr[1] if isinstance(addr, tuple) and len(addr) >= 2 else None
            bind_count += 1

            if bind_count == 1 and port == 0:
                return real_bind(self, addr)

            if fail_once and port != 0:
                fail_once = False
                raise OSError(errno.EADDRINUSE, "simulated collision on second bind")

            return real_bind(self, addr)

        with patch.object(socket.socket, "bind", new=fake_bind):
            async with await create_tcp_listener(
                local_host="localhost", family=socket.AF_UNSPEC, local_port=0
            ) as multi:
                assert bind_count >= 2

                ports = {
                    listener.extra(SocketAttribute.local_port)
                    for listener in multi.listeners
                }
                assert len(ports) == 1
                assert all(
                    isinstance(listener, SocketListener) for listener in multi.listeners
                )

    async def test_tcp_listener_total_bind_failure(self) -> None:
        """
        Test for a situation where bind() always fails when other listeners are being
        bound to the same port as the first listener which was randomly assigned a free
        port by the kernel.
        """

        def raise_oserror(addr: tuple[str, int]) -> None:
            # Pretend that every explicitly requested port is already in use
            if addr[1] != 0:
                raise OSError(errno.EADDRINUSE, "bind failure")

        mock_socket_instance = MagicMock()
        mock_socket_instance.bind.side_effect = raise_oserror
        asynclib = get_async_backend()
        with (
            patch("anyio._core._sockets.socket") as mock_anyio_sockets,
            patch.object(
                asynclib, "create_tcp_listener", return_value=MagicMock(SocketListener)
            ),
            pytest.raises(
                OSError, match="Could not create 2 listeners with a consistent port"
            ),
        ):
            mock_anyio_sockets.socket.configure_mock(return_value=mock_socket_instance)
            await create_tcp_listener(local_host="localhost")


@pytest.mark.skipif(
    sys.platform == "win32", reason="UNIX sockets are not available on Windows"
)
class TestUNIXStream:
    @pytest.fixture(
        params=[
            "path",
            pytest.param("abstract", marks=[skip_unix_abstract_mark]),
        ]
    )
    def socket_path(self, request: SubRequest) -> Generator[Path, None, None]:
        # Use stdlib tempdir generation
        # Fixes `OSError: AF_UNIX path too long` from pytest generated temp_path
        with tempfile.TemporaryDirectory() as path:
            if request.param == "path":
                yield Path(path) / "socket"
            else:
                yield Path(f"\0{path}") / "socket"

    @pytest.fixture(params=[False, True], ids=["str", "path"])
    def socket_path_or_str(self, request: SubRequest, socket_path: Path) -> Path | str:
        return socket_path if request.param else str(socket_path)

    @pytest.fixture
    def server_sock(self, socket_path: Path) -> Iterable[socket.socket]:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1)
        sock.bind(str(socket_path))
        sock.listen()
        yield sock
        sock.close()

    async def test_extra_attributes(
        self, server_sock: socket.socket, socket_path: Path
    ) -> None:
        async with await connect_unix(socket_path) as stream:
            raw_socket = stream.extra(SocketAttribute.raw_socket)
            assert stream.extra(SocketAttribute.family) == socket.AF_UNIX
            assert (
                stream.extra(SocketAttribute.local_address) == raw_socket.getsockname()
            )
            remote_addr = stream.extra(SocketAttribute.remote_address)
            if isinstance(remote_addr, str):
                assert stream.extra(SocketAttribute.remote_address) == str(socket_path)
            else:
                assert isinstance(remote_addr, bytes)
                assert stream.extra(SocketAttribute.remote_address) == bytes(
                    socket_path
                )

            pytest.raises(
                TypedAttributeLookupError, stream.extra, SocketAttribute.local_port
            )
            pytest.raises(
                TypedAttributeLookupError, stream.extra, SocketAttribute.remote_port
            )

    async def test_send_receive(
        self, server_sock: socket.socket, socket_path_or_str: Path | str
    ) -> None:
        async with await connect_unix(socket_path_or_str) as stream:
            client, _ = server_sock.accept()
            await stream.send(b"blah")
            request = client.recv(100)
            client.sendall(request[::-1])
            response = await stream.receive()
            client.close()

        assert response == b"halb"

    async def test_receive_large_buffer(
        self, server_sock: socket.socket, socket_path: Path
    ) -> None:
        def serve() -> None:
            client, _ = server_sock.accept()
            client.sendall(buffer)
            client.close()

        buffer = (
            b"\xff" * 1024 * 512 + b"\x00" * 1024 * 512
        )  # should exceed the maximum kernel send buffer size
        async with await connect_unix(socket_path) as stream:
            thread = Thread(target=serve, daemon=True)
            thread.start()
            response = b""
            while len(response) < len(buffer):
                response += await stream.receive()

        thread.join()
        assert response == buffer

    async def test_send_large_buffer(
        self, server_sock: socket.socket, socket_path: Path
    ) -> None:
        response = b""

        def serve() -> None:
            nonlocal response
            client, _ = server_sock.accept()
            while True:
                data = client.recv(1024)
                if not data:
                    break

                response += data

            client.close()

        buffer = (
            b"\xff" * 1024 * 512 + b"\x00" * 1024 * 512
        )  # should exceed the maximum kernel send buffer size
        async with await connect_unix(socket_path) as stream:
            thread = Thread(target=serve, daemon=True)
            thread.start()
            await stream.send(buffer)

        thread.join()
        assert response == buffer

    async def test_receive_fds(
        self, server_sock: socket.socket, socket_path: Path, tmp_path: Path
    ) -> None:
        def serve() -> None:
            path1 = tmp_path / "file1"
            path2 = tmp_path / "file2"
            path1.write_text("Hello, ")
            path2.write_text("World!")
            with path1.open() as file1, path2.open() as file2:
                fdarray = array.array("i", [file1.fileno(), file2.fileno()])
                client, _ = server_sock.accept()
                cmsg = (socket.SOL_SOCKET, socket.SCM_RIGHTS, fdarray)
                with client:
                    client.sendmsg([b"test"], [cmsg])

        async with await connect_unix(socket_path) as stream:
            thread = Thread(target=serve, daemon=True)
            thread.start()
            message, fds = await stream.receive_fds(10, 2)
            thread.join()

        text = ""
        for fd in fds:
            with os.fdopen(fd) as file:
                text += file.read()

        assert message == b"test"
        assert text == "Hello, World!"

    async def test_receive_fds_bad_args(
        self, server_sock: socket.socket, socket_path: Path
    ) -> None:
        async with await connect_unix(socket_path) as stream:
            for msglen in (-1, "foo"):
                with pytest.raises(
                    ValueError, match="msglen must be a non-negative integer"
                ):
                    await stream.receive_fds(msglen, 0)  # type: ignore[arg-type]

            for maxfds in (0, "foo"):
                with pytest.raises(
                    ValueError, match="maxfds must be a positive integer"
                ):
                    await stream.receive_fds(0, maxfds)  # type: ignore[arg-type]

    async def test_send_fds(
        self, server_sock: socket.socket, socket_path: Path, tmp_path: Path
    ) -> None:
        def serve() -> None:
            fds = array.array("i")
            client, _ = server_sock.accept()
            msg, ancdata, *_ = client.recvmsg(10, socket.CMSG_LEN(2 * fds.itemsize))
            client.close()
            assert msg == b"test"
            for cmsg_level, cmsg_type, cmsg_data in ancdata:
                assert cmsg_level == socket.SOL_SOCKET
                assert cmsg_type == socket.SCM_RIGHTS
                fds.frombytes(
                    cmsg_data[: len(cmsg_data) - (len(cmsg_data) % fds.itemsize)]
                )

            text = ""
            for fd in fds:
                with os.fdopen(fd) as file:
                    text += file.read()

            assert text == "Hello, World!"

        path1 = tmp_path / "file1"
        path2 = tmp_path / "file2"
        path1.write_text("Hello, ")
        path2.write_text("World!")
        with path1.open() as file1, path2.open() as file2, fail_after(2):
            assert isinstance(file1, io.TextIOWrapper)
            assert isinstance(file2, io.TextIOWrapper)
            async with await connect_unix(socket_path) as stream:
                thread = Thread(target=serve, daemon=True)
                thread.start()
                await stream.send_fds(b"test", [file1, file2])
                thread.join()

    async def test_send_eof(
        self, server_sock: socket.socket, socket_path: Path
    ) -> None:
        def serve() -> None:
            client, _ = server_sock.accept()
            request = b""
            while True:
                data = client.recv(100)
                request += data
                if not data:
                    break

            client.sendall(request[::-1])
            client.close()

        async with await connect_unix(socket_path) as stream:
            thread = Thread(target=serve, daemon=True)
            thread.start()
            await stream.send(b"hello, ")
            await stream.send(b"world\n")
            await stream.send_eof()
            response = await stream.receive()

        thread.join()
        assert response == b"\ndlrow ,olleh"

    async def test_iterate(self, server_sock: socket.socket, socket_path: Path) -> None:
        def serve() -> None:
            client, _ = server_sock.accept()
            client.sendall(b"bl")
            time.sleep(0.05)
            client.sendall(b"ah")
            client.close()

        thread = Thread(target=serve, daemon=True)
        thread.start()
        async with await connect_unix(socket_path) as stream:
            chunks = [chunk async for chunk in stream]
        thread.join()
        assert chunks == [b"bl", b"ah"]

    async def test_send_fds_bad_args(
        self, server_sock: socket.socket, socket_path: Path
    ) -> None:
        async with await connect_unix(socket_path) as stream:
            with pytest.raises(ValueError, match="message must not be empty"):
                await stream.send_fds(b"", [0])

            with pytest.raises(ValueError, match="fds must not be empty"):
                await stream.send_fds(b"test", [])

    async def test_concurrent_send(
        self, server_sock: socket.socket, socket_path: Path
    ) -> None:
        async def send_data() -> NoReturn:
            while True:
                await client.send(b"\x00" * 4096)

        async with await connect_unix(socket_path) as client:
            async with create_task_group() as tg:
                tg.start_soon(send_data)
                await wait_all_tasks_blocked()
                with pytest.raises(BusyResourceError) as exc:
                    await client.send(b"foo")

                exc.match("already writing to")
                tg.cancel_scope.cancel()

    async def test_concurrent_receive(
        self, server_sock: socket.socket, socket_path: Path
    ) -> None:
        async with await connect_unix(socket_path) as client:
            async with create_task_group() as tg:
                tg.start_soon(client.receive)
                await wait_all_tasks_blocked()
                try:
                    with pytest.raises(BusyResourceError) as exc:
                        await client.receive()

                    exc.match("already reading from")
                finally:
                    tg.cancel_scope.cancel()

    async def test_close_during_receive(
        self, server_sock: socket.socket, socket_path: Path
    ) -> None:
        async def interrupt() -> None:
            await wait_all_tasks_blocked()
            await stream.aclose()

        async with await connect_unix(socket_path) as stream:
            async with create_task_group() as tg:
                tg.start_soon(interrupt)
                with pytest.raises(ClosedResourceError):
                    await stream.receive()

    async def test_receive_after_close(
        self, server_sock: socket.socket, socket_path: Path
    ) -> None:
        stream = await connect_unix(socket_path)
        await stream.aclose()
        with pytest.raises(ClosedResourceError):
            await stream.receive()

    async def test_send_after_close(
        self, server_sock: socket.socket, socket_path: Path
    ) -> None:
        stream = await connect_unix(socket_path)
        await stream.aclose()
        with pytest.raises(ClosedResourceError):
            await stream.send(b"foo")

    async def test_cannot_connect(self, socket_path: Path) -> None:
        if str(socket_path).startswith("\0"):
            with pytest.raises(ConnectionRefusedError):
                await connect_unix(socket_path)
        else:
            with pytest.raises(FileNotFoundError):
                await connect_unix(socket_path)

    async def test_connecting_using_bytes(
        self, server_sock: socket.socket, socket_path: Path
    ) -> None:
        async with await connect_unix(str(socket_path).encode()):
            pass

    @pytest.mark.skipif(
        platform.system() == "Darwin", reason="macOS requires valid UTF-8 paths"
    )
    async def test_connecting_with_non_utf8(self, socket_path: Path) -> None:
        actual_path = str(socket_path).encode() + b"\xf0"
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(actual_path)
            server.listen(1)

            async with await connect_unix(actual_path):
                pass

    async def test_from_socket(
        self, socket_path: Path, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(
            socket.AF_UNIX, socket.SOCK_STREAM, connected=True
        )
        async with await UNIXSocketStream.from_socket(sock_or_fd) as stream:
            assert isinstance(stream, UNIXSocketStream)

    async def test_from_socket_wrong_socket_type(
        self, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(
            socket.AF_UNIX, socket.SOCK_DGRAM, connected=True
        )
        with pytest.raises(
            ValueError,
            match="socket type mismatch: expected SOCK_STREAM, got SOCK_DGRAM",
        ):
            await UNIXSocketStream.from_socket(sock_or_fd)

    async def test_from_socket_wrong_address_family(
        self, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(
            socket.AF_INET, socket.SOCK_STREAM, connected=True
        )
        with pytest.raises(
            ValueError,
            match="address family mismatch: expected AF_UNIX, got AF_INET",
        ):
            await UNIXSocketStream.from_socket(sock_or_fd)

    async def test_from_socket_not_connected(
        self, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(socket.AF_UNIX, socket.SOCK_STREAM)
        with pytest.raises(ValueError, match="the socket must be connected"):
            await UNIXSocketStream.from_socket(sock_or_fd)


@pytest.mark.skipif(
    sys.platform == "win32", reason="UNIX sockets are not available on Windows"
)
class TestUNIXListener:
    @pytest.fixture(
        params=[
            "path",
            pytest.param("abstract", marks=[skip_unix_abstract_mark]),
        ]
    )
    def socket_path(self, request: SubRequest) -> Generator[Path, None, None]:
        # Use stdlib tempdir generation
        # Fixes `OSError: AF_UNIX path too long` from pytest generated temp_path
        with tempfile.TemporaryDirectory() as path:
            if request.param == "path":
                yield Path(path) / "socket"
            else:
                yield Path(f"\0{path}") / "socket"

    @pytest.fixture(params=[False, True], ids=["str", "path"])
    def socket_path_or_str(self, request: SubRequest, socket_path: Path) -> Path | str:
        return socket_path if request.param else str(socket_path)

    async def test_extra_attributes(self, socket_path: Path) -> None:
        async with await create_unix_listener(socket_path) as listener:
            raw_socket = listener.extra(SocketAttribute.raw_socket)
            assert listener.extra(SocketAttribute.family) == socket.AF_UNIX
            assert (
                listener.extra(SocketAttribute.local_address)
                == raw_socket.getsockname()
            )
            pytest.raises(
                TypedAttributeLookupError, listener.extra, SocketAttribute.local_port
            )
            pytest.raises(
                TypedAttributeLookupError,
                listener.extra,
                SocketAttribute.remote_address,
            )
            pytest.raises(
                TypedAttributeLookupError, listener.extra, SocketAttribute.remote_port
            )

    async def test_accept(self, socket_path_or_str: Path | str) -> None:
        async with await create_unix_listener(socket_path_or_str) as listener:
            client = socket.socket(socket.AF_UNIX)
            client.settimeout(1)
            client.connect(str(socket_path_or_str))
            stream = await listener.accept()
            client.sendall(b"blah")
            request = await stream.receive()
            await stream.send(request[::-1])
            assert client.recv(100) == b"halb"
            client.close()
            await stream.aclose()

    async def test_socket_options(self, socket_path: Path) -> None:
        async with await create_unix_listener(socket_path) as listener:
            listener_socket = listener.extra(SocketAttribute.raw_socket)
            assert listener_socket.family == socket.AF_UNIX
            listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 80000)
            assert listener_socket.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) in (
                80000,
                160000,
            )

            client = socket.socket(listener_socket.family)
            client.settimeout(1)
            client.connect(listener_socket.getsockname())

            async with await listener.accept() as stream:
                assert stream.extra(SocketAttribute.raw_socket).gettimeout() == 0
                assert stream.extra(SocketAttribute.family) == listener_socket.family

            client.close()

    async def test_send_after_eof(self, socket_path: Path) -> None:
        async def handle(stream: SocketStream) -> None:
            async with stream:
                await stream.send(b"Hello\n")

        async with (
            await create_unix_listener(socket_path) as listener,
            create_task_group() as tg,
        ):
            tg.start_soon(listener.serve, handle)
            await wait_all_tasks_blocked()

            with socket.socket(socket.AF_UNIX) as client:
                client.connect(str(socket_path))
                client.shutdown(socket.SHUT_WR)
                client.setblocking(False)
                with fail_after(1):
                    while True:
                        try:
                            message = client.recv(10)
                        except BlockingIOError:
                            await checkpoint()
                        else:
                            assert message == b"Hello\n"
                            break

            tg.cancel_scope.cancel()

    async def test_bind_twice(self, socket_path: Path) -> None:
        """Test that the previous socket is removed before binding to the path."""
        for _ in range(2):
            async with await create_unix_listener(socket_path):
                pass

    async def test_listening_bytes_path(self, socket_path: Path) -> None:
        async with await create_unix_listener(str(socket_path).encode()):
            pass

    @pytest.mark.skipif(
        platform.system() == "Darwin", reason="macOS requires valid UTF-8 paths"
    )
    async def test_listening_invalid_ascii(self, socket_path: Path) -> None:
        real_path = str(socket_path).encode() + b"\xf0"
        async with await create_unix_listener(real_path):
            pass

    async def test_from_socket(self, sock_or_fd_factory: SockFdFactoryProtocol) -> None:
        sock_or_fd = sock_or_fd_factory(socket.AF_UNIX, socket.SOCK_STREAM, bound=True)
        async with await SocketListener.from_socket(sock_or_fd) as listener:
            assert isinstance(listener, SocketListener)
            assert listener.extra(SocketAttribute.family) == socket.AF_UNIX


async def test_multi_listener(tmp_path_factory: TempPathFactory) -> None:
    async def handle(stream: SocketStream) -> None:
        client_addresses.append(stream.extra(SocketAttribute.remote_address))
        event.set()
        await stream.aclose()

    client_addresses: list[str | IPSockAddrType] = []
    listeners: list[Listener] = [await create_tcp_listener(local_host="localhost")]
    with tempfile.TemporaryDirectory() as path:
        if sys.platform != "win32":
            listeners.append(await create_unix_listener(Path(path) / "socket"))

        expected_addresses: list[str | IPSockAddrType] = []
        async with MultiListener(listeners) as multi_listener:
            async with create_task_group() as tg:
                tg.start_soon(multi_listener.serve, handle)
                for listener in multi_listener.listeners:
                    event = Event()
                    local_address = listener.extra(SocketAttribute.local_address)
                    if (
                        sys.platform != "win32"
                        and listener.extra(SocketAttribute.family) == socket.AF_UNIX
                    ):
                        assert isinstance(local_address, str)
                        stream: SocketStream = await connect_unix(local_address)
                    else:
                        assert isinstance(local_address, tuple)
                        host, port = local_address
                        host = (
                            "::1"
                            if listener.extra(SocketAttribute.family) == socket.AF_INET6
                            else "127.0.0.1"
                        )
                        stream = await connect_tcp(host, port)

                    expected_addresses.append(
                        stream.extra(SocketAttribute.local_address)
                    )
                    await event.wait()
                    await stream.aclose()

                tg.cancel_scope.cancel()

        assert client_addresses == expected_addresses


@pytest.mark.network
@pytest.mark.usefixtures("check_asyncio_bug")
class TestUDPSocket:
    async def test_extra_attributes(self, family: AnyIPAddressFamily) -> None:
        async with await create_udp_socket(
            family=family, local_host="localhost"
        ) as udp:
            raw_socket = udp.extra(SocketAttribute.raw_socket)
            assert raw_socket.gettimeout() == 0
            assert udp.extra(SocketAttribute.family) == family
            assert (
                udp.extra(SocketAttribute.local_address) == raw_socket.getsockname()[:2]
            )
            assert udp.extra(SocketAttribute.local_port) == raw_socket.getsockname()[1]
            pytest.raises(
                TypedAttributeLookupError, udp.extra, SocketAttribute.remote_address
            )
            pytest.raises(
                TypedAttributeLookupError, udp.extra, SocketAttribute.remote_port
            )

    async def test_send_receive(self, family: AnyIPAddressFamily) -> None:
        async with await create_udp_socket(
            local_host="localhost", family=family
        ) as sock:
            host, port = sock.extra(SocketAttribute.local_address)  # type: ignore[misc]
            await sock.sendto(b"blah", host, port)
            request, addr = await sock.receive()
            assert request == b"blah"
            assert addr == sock.extra(SocketAttribute.local_address)

            await sock.sendto(b"halb", host, port)
            response, addr = await sock.receive()
            assert response == b"halb"
            assert addr == (host, port)

    async def test_iterate(self, family: AnyIPAddressFamily) -> None:
        async def serve() -> None:
            async for packet, addr in server:
                await server.send((packet[::-1], addr))

        async with await create_udp_socket(
            family=family, local_host="localhost"
        ) as server:
            host, port = server.extra(  # type: ignore[misc]
                SocketAttribute.local_address
            )
            async with await create_udp_socket(
                family=family, local_host="localhost"
            ) as client:
                async with create_task_group() as tg:
                    tg.start_soon(serve)
                    await client.sendto(b"FOOBAR", host, port)
                    assert await client.receive() == (b"RABOOF", (host, port))
                    await client.sendto(b"123456", host, port)
                    assert await client.receive() == (b"654321", (host, port))
                    tg.cancel_scope.cancel()

    @pytest.mark.skipif(
        not hasattr(socket, "SO_REUSEPORT"), reason="SO_REUSEPORT option not supported"
    )
    async def test_reuse_port(self, family: AnyIPAddressFamily) -> None:
        async with await create_udp_socket(
            family=family, local_host="localhost", reuse_port=True
        ) as udp:
            port = udp.extra(SocketAttribute.local_port)
            assert port != 0
            async with await create_udp_socket(
                family=family, local_host="localhost", local_port=port, reuse_port=True
            ) as udp2:
                assert port == udp2.extra(SocketAttribute.local_port)

    async def test_concurrent_receive(self) -> None:
        async with await create_udp_socket(
            family=AddressFamily.AF_INET, local_host="localhost"
        ) as udp:
            async with create_task_group() as tg:
                tg.start_soon(udp.receive)
                await wait_all_tasks_blocked()
                try:
                    with pytest.raises(BusyResourceError) as exc:
                        await udp.receive()

                    exc.match("already reading from")
                finally:
                    tg.cancel_scope.cancel()

    async def test_close_during_receive(self) -> None:
        async def close_when_blocked() -> None:
            await wait_all_tasks_blocked()
            await udp.aclose()

        async with await create_udp_socket(
            family=AddressFamily.AF_INET, local_host="localhost"
        ) as udp:
            async with create_task_group() as tg:
                tg.start_soon(close_when_blocked)
                with pytest.raises(ClosedResourceError):
                    await udp.receive()

    async def test_receive_after_close(self) -> None:
        udp = await create_udp_socket(
            family=AddressFamily.AF_INET, local_host="localhost"
        )
        await udp.aclose()
        with pytest.raises(ClosedResourceError):
            await udp.receive()

    async def test_send_after_close(self) -> None:
        udp = await create_udp_socket(
            family=AddressFamily.AF_INET, local_host="localhost"
        )
        host, port = udp.extra(SocketAttribute.local_address)  # type: ignore[misc]
        await udp.aclose()
        with pytest.raises(ClosedResourceError):
            await udp.sendto(b"foo", host, port)

    async def test_create_unbound_socket(self, family: AnyIPAddressFamily) -> None:
        """Regression test for #360."""
        async with await create_udp_socket(family=family) as udp:
            local_address = cast(
                IPSockAddrType, udp.extra(SocketAttribute.local_address)
            )
            assert local_address[1] > 0

    async def test_from_socket(
        self, family: AnyIPAddressFamily, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(family, socket.SOCK_DGRAM, bound=True)
        async with await UDPSocket.from_socket(sock_or_fd) as udp_socket:
            assert isinstance(udp_socket, UDPSocket)
            assert udp_socket.extra(SocketAttribute.family) == family

    async def test_from_socket_wrong_socket_type(
        self, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(
            socket.AF_INET, socket.SOCK_STREAM, connected=True
        )
        with pytest.raises(
            ValueError,
            match="socket type mismatch: expected SOCK_DGRAM, got SOCK_STREAM",
        ):
            await UDPSocket.from_socket(sock_or_fd)


@pytest.mark.network
@pytest.mark.usefixtures("check_asyncio_bug")
class TestConnectedUDPSocket:
    async def test_extra_attributes(self, family: AnyIPAddressFamily) -> None:
        async with await create_connected_udp_socket(
            "localhost", 5000, family=family
        ) as udp:
            raw_socket = udp.extra(SocketAttribute.raw_socket)
            assert udp.extra(SocketAttribute.family) == family
            assert (
                udp.extra(SocketAttribute.local_address) == raw_socket.getsockname()[:2]
            )
            assert udp.extra(SocketAttribute.local_port) == raw_socket.getsockname()[1]
            assert (
                udp.extra(SocketAttribute.remote_address)
                == raw_socket.getpeername()[:2]
            )
            assert udp.extra(SocketAttribute.remote_port) == 5000

    async def test_send_receive(self, family: AnyIPAddressFamily) -> None:
        async with await create_udp_socket(
            family=family, local_host="localhost"
        ) as udp1:
            host, port = udp1.extra(SocketAttribute.local_address)  # type: ignore[misc]
            async with await create_connected_udp_socket(
                host, port, local_host="localhost", family=family
            ) as udp2:
                host, port = udp2.extra(
                    SocketAttribute.local_address  # type: ignore[misc]
                )
                await udp2.send(b"blah")
                request = await udp1.receive()
                assert request == (b"blah", (host, port))

                await udp1.sendto(b"halb", host, port)
                response = await udp2.receive()
                assert response == b"halb"

    async def test_iterate(self, family: AnyIPAddressFamily) -> None:
        async def serve() -> None:
            async for packet in udp2:
                await udp2.send(packet[::-1])

        async with await create_udp_socket(
            family=family, local_host="localhost"
        ) as udp1:
            host, port = udp1.extra(SocketAttribute.local_address)  # type: ignore[misc]
            async with await create_connected_udp_socket(host, port) as udp2:
                host, port = udp2.extra(  # type: ignore[misc]
                    SocketAttribute.local_address
                )
                async with create_task_group() as tg:
                    tg.start_soon(serve)
                    await udp1.sendto(b"FOOBAR", host, port)
                    assert await udp1.receive() == (b"RABOOF", (host, port))
                    await udp1.sendto(b"123456", host, port)
                    assert await udp1.receive() == (b"654321", (host, port))
                    tg.cancel_scope.cancel()

    @pytest.mark.skipif(
        not hasattr(socket, "SO_REUSEPORT"), reason="SO_REUSEPORT option not supported"
    )
    async def test_reuse_port(self, family: AnyIPAddressFamily) -> None:
        async with await create_connected_udp_socket(
            "localhost", 6000, family=family, local_host="localhost", reuse_port=True
        ) as udp:
            port = udp.extra(SocketAttribute.local_port)
            assert port != 0
            async with await create_connected_udp_socket(
                "localhost",
                6001,
                family=family,
                local_host="localhost",
                local_port=port,
                reuse_port=True,
            ) as udp2:
                assert port == udp2.extra(SocketAttribute.local_port)

    async def test_concurrent_receive(self) -> None:
        async with await create_connected_udp_socket(
            "localhost", 5000, local_host="localhost", family=AddressFamily.AF_INET
        ) as udp:
            async with create_task_group() as tg:
                tg.start_soon(udp.receive)
                await wait_all_tasks_blocked()
                try:
                    with pytest.raises(BusyResourceError) as exc:
                        await udp.receive()

                    exc.match("already reading from")
                finally:
                    tg.cancel_scope.cancel()

    async def test_close_during_receive(self) -> None:
        async def close_when_blocked() -> None:
            await wait_all_tasks_blocked()
            await udp.aclose()

        async with await create_connected_udp_socket(
            "localhost", 5000, local_host="localhost", family=AddressFamily.AF_INET
        ) as udp:
            async with create_task_group() as tg:
                tg.start_soon(close_when_blocked)
                with pytest.raises(ClosedResourceError):
                    await udp.receive()

    async def test_receive_after_close(self, family: AnyIPAddressFamily) -> None:
        udp = await create_connected_udp_socket(
            "localhost", 5000, local_host="localhost", family=family
        )
        await udp.aclose()
        with pytest.raises(ClosedResourceError):
            await udp.receive()

    async def test_send_after_close(self, family: AnyIPAddressFamily) -> None:
        udp = await create_connected_udp_socket(
            "localhost", 5000, local_host="localhost", family=family
        )
        await udp.aclose()
        with pytest.raises(ClosedResourceError):
            await udp.send(b"foo")

    async def test_from_socket(
        self, family: AnyIPAddressFamily, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(family, socket.SOCK_DGRAM, connected=True)
        async with await ConnectedUDPSocket.from_socket(sock_or_fd) as udp_socket:
            assert isinstance(udp_socket, ConnectedUDPSocket)
            assert udp_socket.extra(SocketAttribute.family) == family

    async def test_from_socket_wrong_socket_type(
        self, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(
            socket.AF_INET, socket.SOCK_STREAM, connected=True
        )
        with pytest.raises(
            ValueError,
            match="socket type mismatch: expected SOCK_DGRAM, got SOCK_STREAM",
        ):
            await ConnectedUDPSocket.from_socket(sock_or_fd)

    async def test_from_socket_not_connected(
        self, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(socket.AF_INET, socket.SOCK_DGRAM, bound=True)
        with pytest.raises(ValueError, match="the socket must be connected"):
            await ConnectedUDPSocket.from_socket(sock_or_fd)


@pytest.mark.skipif(
    sys.platform == "win32", reason="UNIX sockets are not available on Windows"
)
class TestUNIXDatagramSocket:
    @pytest.fixture(
        params=[
            "path",
            pytest.param("abstract", marks=[skip_unix_abstract_mark]),
        ]
    )
    def socket_path(self, request: SubRequest) -> Generator[Path, None, None]:
        # Use stdlib tempdir generation
        # Fixes `OSError: AF_UNIX path too long` from pytest generated temp_path
        with tempfile.TemporaryDirectory() as path:
            if request.param == "path":
                yield Path(path) / "socket"
            else:
                yield Path(f"\0{path}") / "socket"

    @pytest.fixture(params=[False, True], ids=["str", "path"])
    def socket_path_or_str(self, request: SubRequest, socket_path: Path) -> Path | str:
        return socket_path if request.param else str(socket_path)

    @pytest.fixture
    def peer_socket_path(self) -> Generator[Path, None, None]:
        # Use stdlib tempdir generation
        # Fixes `OSError: AF_UNIX path too long` from pytest generated temp_path
        with tempfile.TemporaryDirectory() as path:
            yield Path(path) / "peer_socket"

    async def test_extra_attributes(self, socket_path: Path) -> None:
        async with await create_unix_datagram_socket(local_path=socket_path) as unix_dg:
            raw_socket = unix_dg.extra(SocketAttribute.raw_socket)
            assert raw_socket.gettimeout() == 0
            assert unix_dg.extra(SocketAttribute.family) == socket.AF_UNIX
            assert (
                unix_dg.extra(SocketAttribute.local_address) == raw_socket.getsockname()
            )
            pytest.raises(
                TypedAttributeLookupError, unix_dg.extra, SocketAttribute.local_port
            )
            pytest.raises(
                TypedAttributeLookupError, unix_dg.extra, SocketAttribute.remote_address
            )
            pytest.raises(
                TypedAttributeLookupError, unix_dg.extra, SocketAttribute.remote_port
            )

    async def test_send_receive(self, socket_path_or_str: Path | str) -> None:
        async with await create_unix_datagram_socket(
            local_path=socket_path_or_str,
        ) as sock:
            path = str(socket_path_or_str)

            await sock.sendto(b"blah", path)
            request, addr = await sock.receive()
            assert request == b"blah"
            if isinstance(addr, bytes):
                assert addr == path.encode()
            else:
                assert addr == path

            await sock.sendto(b"halb", path)
            response, addr = await sock.receive()
            assert response == b"halb"
            if isinstance(addr, bytes):
                assert addr == path.encode()
            else:
                assert addr == path

    async def test_iterate(self, peer_socket_path: Path, socket_path: Path) -> None:
        async def serve() -> None:
            async for packet, addr in server:
                await server.send((packet[::-1], addr))

        async with await create_unix_datagram_socket(
            local_path=peer_socket_path,
        ) as server:
            peer_path = str(peer_socket_path)
            async with await create_unix_datagram_socket(
                local_path=socket_path
            ) as client:
                async with create_task_group() as tg:
                    tg.start_soon(serve)
                    await client.sendto(b"FOOBAR", peer_path)
                    assert await client.receive() == (b"RABOOF", peer_path)
                    await client.sendto(b"123456", peer_path)
                    assert await client.receive() == (b"654321", peer_path)
                    tg.cancel_scope.cancel()

    async def test_concurrent_receive(self) -> None:
        async with await create_unix_datagram_socket() as unix_dg:
            async with create_task_group() as tg:
                tg.start_soon(unix_dg.receive)
                await wait_all_tasks_blocked()
                try:
                    with pytest.raises(BusyResourceError) as exc:
                        await unix_dg.receive()

                    exc.match("already reading from")
                finally:
                    tg.cancel_scope.cancel()

    async def test_close_during_receive(self) -> None:
        async def close_when_blocked() -> None:
            await wait_all_tasks_blocked()
            await unix_dg.aclose()

        async with await create_unix_datagram_socket() as unix_dg:
            async with create_task_group() as tg:
                tg.start_soon(close_when_blocked)
                with pytest.raises(ClosedResourceError):
                    await unix_dg.receive()

    async def test_receive_after_close(self) -> None:
        unix_dg = await create_unix_datagram_socket()
        await unix_dg.aclose()
        with pytest.raises(ClosedResourceError):
            await unix_dg.receive()

    async def test_send_after_close(self, socket_path: Path) -> None:
        unix_dg = await create_unix_datagram_socket(local_path=socket_path)
        path = str(socket_path)
        await unix_dg.aclose()
        with pytest.raises(ClosedResourceError):
            await unix_dg.sendto(b"foo", path)

    async def test_local_path_bytes(self, socket_path: Path) -> None:
        async with await create_unix_datagram_socket(
            local_path=str(socket_path).encode()
        ):
            pass

    @pytest.mark.skipif(
        platform.system() == "Darwin", reason="macOS requires valid UTF-8 paths"
    )
    async def test_local_path_invalid_ascii(self, socket_path: Path) -> None:
        real_path = str(socket_path).encode() + b"\xf0"
        async with await create_unix_datagram_socket(local_path=real_path):
            pass

    async def test_from_socket(self, sock_or_fd_factory: SockFdFactoryProtocol) -> None:
        sock_or_fd = sock_or_fd_factory(socket.AF_UNIX, socket.SOCK_DGRAM)
        async with await UNIXDatagramSocket.from_socket(sock_or_fd) as udp_socket:
            assert isinstance(udp_socket, UNIXDatagramSocket)
            assert udp_socket.extra(SocketAttribute.family) == socket.AF_UNIX

    async def test_from_socket_wrong_socket_type(
        self, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(socket.AF_UNIX, socket.SOCK_STREAM)
        with pytest.raises(
            ValueError,
            match="socket type mismatch: expected SOCK_DGRAM, got SOCK_STREAM",
        ):
            await UNIXDatagramSocket.from_socket(sock_or_fd)


@pytest.mark.skipif(
    sys.platform == "win32", reason="UNIX sockets are not available on Windows"
)
class TestConnectedUNIXDatagramSocket:
    @pytest.fixture(
        params=[
            "path",
            pytest.param("abstract", marks=[skip_unix_abstract_mark]),
        ]
    )
    def socket_path(self, request: SubRequest) -> Generator[Path, None, None]:
        # Use stdlib tempdir generation
        # Fixes `OSError: AF_UNIX path too long` from pytest generated temp_path
        with tempfile.TemporaryDirectory() as path:
            if request.param == "path":
                yield Path(path) / "socket"
            else:
                yield Path(f"\0{path}") / "socket"

    @pytest.fixture(params=[False, True], ids=["str", "path"])
    def socket_path_or_str(self, request: SubRequest, socket_path: Path) -> Path | str:
        return socket_path if request.param else str(socket_path)

    @pytest.fixture(
        params=[
            pytest.param("path", id="path-peer"),
            pytest.param(
                "abstract", marks=[skip_unix_abstract_mark], id="abstract-peer"
            ),
        ]
    )
    def peer_socket_path(self) -> Generator[Path, None, None]:
        # Use stdlib tempdir generation
        # Fixes `OSError: AF_UNIX path too long` from pytest generated temp_path
        with tempfile.TemporaryDirectory() as path:
            yield Path(path) / "peer_socket"

    @pytest.fixture(params=[False, True], ids=["peer_str", "peer_path"])
    def peer_socket_path_or_str(
        self, request: SubRequest, peer_socket_path: Path
    ) -> Path | str:
        return peer_socket_path if request.param else str(peer_socket_path)

    @pytest.fixture
    def peer_sock(self, peer_socket_path: Path) -> Iterable[socket.socket]:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.settimeout(1)
        sock.bind(str(peer_socket_path))
        yield sock
        sock.close()

    async def test_extra_attributes(
        self,
        socket_path: Path,
        peer_socket_path: Path,
        peer_sock: socket.socket,
    ) -> None:
        async with await create_connected_unix_datagram_socket(
            remote_path=peer_socket_path,
            local_path=socket_path,
        ) as unix_dg:
            raw_socket = unix_dg.extra(SocketAttribute.raw_socket)
            assert raw_socket is not None
            assert unix_dg.extra(SocketAttribute.family) == AddressFamily.AF_UNIX
            assert os.fsencode(
                cast(os.PathLike, unix_dg.extra(SocketAttribute.local_address))
            ) == os.fsencode(socket_path)
            assert os.fsencode(
                cast(os.PathLike, unix_dg.extra(SocketAttribute.remote_address))
            ) == os.fsencode(peer_socket_path)
            pytest.raises(
                TypedAttributeLookupError, unix_dg.extra, SocketAttribute.local_port
            )
            pytest.raises(
                TypedAttributeLookupError, unix_dg.extra, SocketAttribute.remote_port
            )

    async def test_send_receive(
        self,
        socket_path_or_str: Path | str,
        peer_socket_path_or_str: Path | str,
    ) -> None:
        async with await create_unix_datagram_socket(
            local_path=peer_socket_path_or_str,
        ) as unix_dg1:
            async with await create_connected_unix_datagram_socket(
                peer_socket_path_or_str,
                local_path=socket_path_or_str,
            ) as unix_dg2:
                socket_path = os.fsdecode(socket_path_or_str)

                await unix_dg2.send(b"blah")
                data, remote_addr = await unix_dg1.receive()
                assert (data, os.fsdecode(remote_addr)) == (b"blah", socket_path)

                await unix_dg1.sendto(b"halb", socket_path)
                response = await unix_dg2.receive()
                assert response == b"halb"

    async def test_iterate(
        self,
        socket_path: Path,
        peer_socket_path: Path,
    ) -> None:
        async def serve() -> None:
            async for packet in unix_dg2:
                await unix_dg2.send(packet[::-1])

        async with await create_unix_datagram_socket(
            local_path=peer_socket_path,
        ) as unix_dg1:
            async with await create_connected_unix_datagram_socket(
                peer_socket_path, local_path=socket_path
            ) as unix_dg2:
                path = os.fsdecode(socket_path)
                async with create_task_group() as tg:
                    tg.start_soon(serve)
                    await unix_dg1.sendto(b"FOOBAR", path)
                    data, addr = await unix_dg1.receive()
                    assert (data, os.fsdecode(addr)) == (b"RABOOF", path)
                    await unix_dg1.sendto(b"123456", path)
                    data, addr = await unix_dg1.receive()
                    assert (data, os.fsdecode(addr)) == (b"654321", path)
                    tg.cancel_scope.cancel()

    async def test_concurrent_receive(
        self, peer_socket_path: Path, peer_sock: socket.socket
    ) -> None:
        async with await create_connected_unix_datagram_socket(
            peer_socket_path
        ) as unix_dg:
            async with create_task_group() as tg:
                tg.start_soon(unix_dg.receive)
                await wait_all_tasks_blocked()
                try:
                    with pytest.raises(BusyResourceError) as exc:
                        await unix_dg.receive()

                    exc.match("already reading from")
                finally:
                    tg.cancel_scope.cancel()

    async def test_close_during_receive(
        self, peer_socket_path_or_str: Path | str, peer_sock: socket.socket
    ) -> None:
        async def close_when_blocked() -> None:
            await wait_all_tasks_blocked()
            await udp.aclose()

        async with await create_connected_unix_datagram_socket(
            peer_socket_path_or_str
        ) as udp:
            async with create_task_group() as tg:
                tg.start_soon(close_when_blocked)
                with pytest.raises(ClosedResourceError):
                    await udp.receive()

    async def test_receive_after_close(
        self, peer_socket_path_or_str: Path | str, peer_sock: socket.socket
    ) -> None:
        udp = await create_connected_unix_datagram_socket(peer_socket_path_or_str)
        await udp.aclose()
        with pytest.raises(ClosedResourceError):
            await udp.receive()

    async def test_send_after_close(
        self, peer_socket_path_or_str: Path | str, peer_sock: socket.socket
    ) -> None:
        udp = await create_connected_unix_datagram_socket(peer_socket_path_or_str)
        await udp.aclose()
        with pytest.raises(ClosedResourceError):
            await udp.send(b"foo")

    async def test_from_socket(self, sock_or_fd_factory: SockFdFactoryProtocol) -> None:
        sock_or_fd = sock_or_fd_factory(
            socket.AF_UNIX, socket.SOCK_DGRAM, connected=True
        )
        async with await ConnectedUNIXDatagramSocket.from_socket(
            sock_or_fd
        ) as udp_socket:
            assert isinstance(udp_socket, ConnectedUNIXDatagramSocket)
            assert udp_socket.extra(SocketAttribute.family) == socket.AF_UNIX

    async def test_from_socket_wrong_socket_type(
        self, socket_path: Path, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(
            socket.AF_UNIX, socket.SOCK_STREAM, connected=True
        )
        with pytest.raises(
            ValueError,
            match="socket type mismatch: expected SOCK_DGRAM, got SOCK_STREAM",
        ):
            await ConnectedUNIXDatagramSocket.from_socket(sock_or_fd)

    async def test_from_socket_not_connected(
        self, sock_or_fd_factory: SockFdFactoryProtocol
    ) -> None:
        sock_or_fd = sock_or_fd_factory(socket.AF_UNIX, socket.SOCK_DGRAM, bound=True)
        with pytest.raises(ValueError, match="the socket must be connected"):
            await ConnectedUNIXDatagramSocket.from_socket(sock_or_fd)


async def test_tcp_connectable(mocker: MockerFixture) -> None:
    mock_connect_tcp = mocker.patch("anyio._core._sockets.connect_tcp")
    connectable = TCPConnectable("localhost", 1234)
    await connectable.connect()
    mock_connect_tcp.assert_called_once_with("localhost", 1234)


async def test_unix_connectable(mocker: MockerFixture) -> None:
    mock_connect_tcp = mocker.patch("anyio._core._sockets.connect_unix")
    connectable = UNIXConnectable("/foo/bar")
    await connectable.connect()
    mock_connect_tcp.assert_called_once_with("/foo/bar")


class TestAsConnectable:
    def test_pass_connectable(self) -> None:
        connectable = TCPConnectable("localhost", 1234)
        assert as_connectable(connectable) is connectable

    @pytest.mark.parametrize(
        "addr",
        [
            pytest.param("localhost", id="string"),
            pytest.param(IPv4Address("127.0.0.1"), id="ipv4addr"),
            pytest.param(IPv6Address("::1"), id="ipv6addr"),
        ],
    )
    def test_tcp(self, addr: str | IPv4Address | IPv6Address) -> None:
        connectable = as_connectable((addr, 1234))
        assert isinstance(connectable, TCPConnectable)
        assert connectable.host == addr
        assert connectable.port == 1234

    @pytest.mark.parametrize(
        "path",
        [
            pytest.param("/foo/bar", id="str"),
            pytest.param(b"/foo/bar", id="bytes"),
            pytest.param(Path("/foo/bar"), id="strpath"),
        ],
    )
    def test_unix(self, path: str | bytes | os.PathLike[str]) -> None:
        connectable = as_connectable(path)
        assert isinstance(connectable, UNIXConnectable)
        assert connectable.path == path

    def test_bad_type(self) -> None:
        with pytest.raises(TypeError, match="cannot convert 1234 to a connectable"):
            as_connectable(1234)  # type: ignore[arg-type]

    def test_tls_true(self) -> None:
        connectable = as_connectable(
            "/foo/bar",
            tls=True,
            tls_hostname="example.com",
            tls_standard_compatible=False,
        )
        assert isinstance(connectable, TLSConnectable)
        assert connectable.hostname == "example.com"
        assert not connectable.standard_compatible
        assert isinstance(connectable, TLSConnectable)

    def test_tls_explicit_context(self, client_context: SSLContext) -> None:
        connectable = as_connectable(
            "/foo/bar", tls=True, ssl_context=client_context, tls_hostname="example.com"
        )
        assert isinstance(connectable, TLSConnectable)
        assert connectable.ssl_context is client_context
        assert connectable.hostname == "example.com"

    def test_tls_tcp_implicit_hostname(self, client_context: SSLContext) -> None:
        connectable = as_connectable(("localhost", 1234), tls=True)
        assert isinstance(connectable, TLSConnectable)
        assert connectable.hostname == "localhost"


@pytest.mark.network
async def test_getaddrinfo() -> None:
    # IDNA 2003 gets this wrong
    correct = await getaddrinfo("faß.de", 0)
    wrong = await getaddrinfo("fass.de", 0)
    assert correct != wrong


@pytest.mark.parametrize("sock_type", [socket.SOCK_STREAM, socket.SOCK_STREAM])
async def test_getaddrinfo_ipv6addr(
    sock_type: Literal[socket.SocketKind.SOCK_STREAM],
) -> None:
    # IDNA trips up over raw IPv6 addresses
    proto = 0 if platform.system() == "Windows" else 6
    assert await getaddrinfo("::1", 0, type=sock_type) == [
        (
            socket.AF_INET6,
            socket.SOCK_STREAM,
            proto,
            "",
            ("::1", 0),
        )
    ]


async def test_getaddrinfo_ipv6_disabled() -> None:
    gai_result = [(AddressFamily.AF_INET6, socket.SOCK_STREAM, 6, "", (1, b""))]
    with mock.patch.object(get_async_backend(), "getaddrinfo", return_value=gai_result):
        assert await getaddrinfo("::1", 0) == []


async def test_getnameinfo() -> None:
    expected_result = socket.getnameinfo(("127.0.0.1", 6666), 0)
    result = await getnameinfo(("127.0.0.1", 6666))
    assert result == expected_result


async def test_connect_tcp_getaddrinfo_context() -> None:
    """
    See https://github.com/agronholm/anyio/issues/815
    """
    with pytest.raises(socket.gaierror) as exc_info:
        async with await connect_tcp("anyio.invalid", 6666):
            pass

    assert exc_info.value.__context__ is None


@pytest.mark.parametrize("socket_type", ["socket", "fd"])
@pytest.mark.parametrize("event", ["readable", "writable"])
async def test_wait_socket(event: str, socket_type: str) -> None:
    wait = wait_readable if event == "readable" else wait_writable

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.bind(("127.0.0.1", 0))
        port = server_sock.getsockname()[1]
        server_sock.listen()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_sock:
            client_sock.connect(("127.0.0.1", port))
            client_sock.sendall(b"Hello, world")

        conn, addr = server_sock.accept()
        with conn:
            sock_or_fd: FileDescriptorLike = (
                conn.fileno() if socket_type == "fd" else conn
            )
            with fail_after(3):
                await wait(sock_or_fd)
                assert conn.recv(1024) == b"Hello, world"


async def test_deprecated_wait_socket(anyio_backend_name: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.warns(
            DeprecationWarning,
            match="This function is deprecated; use `wait_readable` instead",
        ):
            with move_on_after(0.1):
                await wait_socket_readable(sock)

        with pytest.warns(
            DeprecationWarning,
            match="This function is deprecated; use `wait_writable` instead",
        ):
            with move_on_after(0.1):
                await wait_socket_writable(sock)


@pytest.mark.parametrize("socket_type", ["socket", "fd"])
async def test_interrupted_by_close(socket_type: str) -> None:
    a_sock, b = socket.socketpair()
    with a_sock, b:
        a_sock.setblocking(False)
        b.setblocking(False)

        a: FileDescriptorLike = a_sock.fileno() if socket_type == "fd" else a_sock

        async def reader() -> None:
            with pytest.raises(ClosedResourceError):
                await wait_readable(a)

        async def writer() -> None:
            with pytest.raises(ClosedResourceError):
                await wait_writable(a)

        fill_socket(a_sock)

        async with create_task_group() as tg:
            tg.start_soon(reader)
            tg.start_soon(writer)
            await wait_all_tasks_blocked()
            notify_closing(a_sock)
            a_sock.close()
