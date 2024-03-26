from __future__ import annotations

import socket
import ssl
from contextlib import ExitStack
from threading import Thread
from typing import ContextManager, NoReturn

import pytest
from pytest_mock import MockerFixture
from trustme import CA

from anyio import (
    BrokenResourceError,
    EndOfStream,
    Event,
    connect_tcp,
    create_memory_object_stream,
    create_task_group,
    create_tcp_listener,
    to_thread,
)
from anyio.abc import AnyByteStream, SocketAttribute, SocketStream
from anyio.streams.stapled import StapledObjectStream
from anyio.streams.tls import TLSAttribute, TLSListener, TLSStream

pytestmark = pytest.mark.anyio


class TestTLSStream:
    async def test_send_receive(
        self, server_context: ssl.SSLContext, client_context: ssl.SSLContext
    ) -> None:
        def serve_sync() -> None:
            conn, addr = server_sock.accept()
            conn.settimeout(1)
            data = conn.recv(10)
            conn.send(data[::-1])
            conn.close()

        server_sock = server_context.wrap_socket(
            socket.socket(), server_side=True, suppress_ragged_eofs=False
        )
        server_sock.settimeout(1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync)
        server_thread.start()

        async with await connect_tcp(*server_sock.getsockname()) as stream:
            wrapper = await TLSStream.wrap(
                stream, hostname="localhost", ssl_context=client_context
            )
            await wrapper.send(b"hello")
            response = await wrapper.receive()

        server_thread.join()
        server_sock.close()
        assert response == b"olleh"

    async def test_extra_attributes(
        self, server_context: ssl.SSLContext, client_context: ssl.SSLContext
    ) -> None:
        def serve_sync() -> None:
            conn, addr = server_sock.accept()
            with conn:
                conn.settimeout(1)
                conn.recv(1)

        server_context.set_alpn_protocols(["h2"])
        client_context.set_alpn_protocols(["h2"])

        server_sock = server_context.wrap_socket(
            socket.socket(), server_side=True, suppress_ragged_eofs=True
        )
        server_sock.settimeout(1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync)
        server_thread.start()

        async with await connect_tcp(*server_sock.getsockname()) as stream:
            wrapper = await TLSStream.wrap(
                stream,
                hostname="localhost",
                ssl_context=client_context,
                standard_compatible=False,
            )
            async with wrapper:
                for name, attribute in SocketAttribute.__dict__.items():
                    if not name.startswith("_"):
                        assert wrapper.extra(attribute) == stream.extra(attribute)

                assert wrapper.extra(TLSAttribute.alpn_protocol) == "h2"
                assert isinstance(
                    wrapper.extra(TLSAttribute.channel_binding_tls_unique), bytes
                )
                assert isinstance(wrapper.extra(TLSAttribute.cipher), tuple)
                assert isinstance(wrapper.extra(TLSAttribute.peer_certificate), dict)
                assert isinstance(
                    wrapper.extra(TLSAttribute.peer_certificate_binary), bytes
                )
                assert wrapper.extra(TLSAttribute.server_side) is False
                assert wrapper.extra(TLSAttribute.shared_ciphers) is None
                assert isinstance(wrapper.extra(TLSAttribute.ssl_object), ssl.SSLObject)
                assert wrapper.extra(TLSAttribute.standard_compatible) is False
                assert wrapper.extra(TLSAttribute.tls_version).startswith("TLSv")
                await wrapper.send(b"\x00")

        server_thread.join()
        server_sock.close()

    async def test_unwrap(
        self, server_context: ssl.SSLContext, client_context: ssl.SSLContext
    ) -> None:
        def serve_sync() -> None:
            conn, addr = server_sock.accept()
            conn.settimeout(1)
            conn.send(b"encrypted")
            unencrypted = conn.unwrap()
            unencrypted.send(b"unencrypted")
            unencrypted.close()

        server_sock = server_context.wrap_socket(
            socket.socket(), server_side=True, suppress_ragged_eofs=False
        )
        server_sock.settimeout(1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync)
        server_thread.start()

        async with await connect_tcp(*server_sock.getsockname()) as stream:
            wrapper = await TLSStream.wrap(
                stream, hostname="localhost", ssl_context=client_context
            )
            msg1 = await wrapper.receive()
            unwrapped_stream, msg2 = await wrapper.unwrap()
            if msg2 != b"unencrypted":
                msg2 += await unwrapped_stream.receive()

        server_thread.join()
        server_sock.close()
        assert msg1 == b"encrypted"
        assert msg2 == b"unencrypted"

    @pytest.mark.skipif(not ssl.HAS_ALPN, reason="ALPN support not available")
    async def test_alpn_negotiation(
        self, server_context: ssl.SSLContext, client_context: ssl.SSLContext
    ) -> None:
        def serve_sync() -> None:
            conn, addr = server_sock.accept()
            conn.settimeout(1)
            selected_alpn_protocol = conn.selected_alpn_protocol()
            assert selected_alpn_protocol is not None
            conn.send(selected_alpn_protocol.encode())
            conn.close()

        server_context.set_alpn_protocols(["dummy1", "dummy2"])
        client_context.set_alpn_protocols(["dummy2", "dummy3"])

        server_sock = server_context.wrap_socket(
            socket.socket(), server_side=True, suppress_ragged_eofs=False
        )
        server_sock.settimeout(1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync)
        server_thread.start()

        async with await connect_tcp(*server_sock.getsockname()) as stream:
            wrapper = await TLSStream.wrap(
                stream, hostname="localhost", ssl_context=client_context
            )
            assert wrapper.extra(TLSAttribute.alpn_protocol) == "dummy2"
            server_alpn_protocol = await wrapper.receive()

        server_thread.join()
        server_sock.close()
        assert server_alpn_protocol == b"dummy2"

    @pytest.mark.parametrize(
        "server_compatible, client_compatible",
        [
            pytest.param(True, True, id="both_standard"),
            pytest.param(True, False, id="server_standard"),
            pytest.param(False, True, id="client_standard"),
            pytest.param(False, False, id="neither_standard"),
        ],
    )
    async def test_ragged_eofs(
        self,
        server_context: ssl.SSLContext,
        client_context: ssl.SSLContext,
        server_compatible: bool,
        client_compatible: bool,
    ) -> None:
        server_exc = None

        def serve_sync() -> None:
            nonlocal server_exc
            conn, addr = server_sock.accept()
            try:
                conn.settimeout(1)
                conn.sendall(b"hello")
                if server_compatible:
                    conn.unwrap()
            except BaseException as exc:
                server_exc = exc
            finally:
                conn.close()

        client_cm: ContextManager = ExitStack()
        if client_compatible and not server_compatible:
            client_cm = pytest.raises(BrokenResourceError)

        server_sock = server_context.wrap_socket(
            socket.socket(),
            server_side=True,
            suppress_ragged_eofs=not server_compatible,
        )
        server_sock.settimeout(1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync, daemon=True)
        server_thread.start()

        async with await connect_tcp(*server_sock.getsockname()) as stream:
            wrapper = await TLSStream.wrap(
                stream,
                hostname="localhost",
                ssl_context=client_context,
                standard_compatible=client_compatible,
            )
            with client_cm:
                assert await wrapper.receive() == b"hello"
                await wrapper.aclose()

        server_thread.join()
        server_sock.close()
        if not client_compatible and server_compatible:
            assert isinstance(server_exc, OSError)
            assert not isinstance(server_exc, socket.timeout)
        else:
            assert server_exc is None

    async def test_ragged_eof_on_receive(
        self, server_context: ssl.SSLContext, client_context: ssl.SSLContext
    ) -> None:
        server_exc = None

        def serve_sync() -> None:
            nonlocal server_exc
            conn, addr = server_sock.accept()
            try:
                conn.settimeout(1)
                conn.sendall(b"hello")
            except BaseException as exc:
                server_exc = exc
            finally:
                conn.close()

        server_sock = server_context.wrap_socket(
            socket.socket(), server_side=True, suppress_ragged_eofs=True
        )
        server_sock.settimeout(1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync, daemon=True)
        server_thread.start()
        try:
            async with await connect_tcp(*server_sock.getsockname()) as stream:
                wrapper = await TLSStream.wrap(
                    stream,
                    hostname="localhost",
                    ssl_context=client_context,
                    standard_compatible=False,
                )
                assert await wrapper.receive() == b"hello"
                with pytest.raises(EndOfStream):
                    await wrapper.receive()
        finally:
            server_thread.join()
            server_sock.close()

        assert server_exc is None

    async def test_receive_send_after_eof(
        self, server_context: ssl.SSLContext, client_context: ssl.SSLContext
    ) -> None:
        def serve_sync() -> None:
            conn, addr = server_sock.accept()
            conn.sendall(b"hello")
            conn.unwrap()
            conn.close()

        server_sock = server_context.wrap_socket(
            socket.socket(), server_side=True, suppress_ragged_eofs=False
        )
        server_sock.settimeout(1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync, daemon=True)
        server_thread.start()

        stream = await connect_tcp(*server_sock.getsockname())
        async with await TLSStream.wrap(
            stream, hostname="localhost", ssl_context=client_context
        ) as wrapper:
            assert await wrapper.receive() == b"hello"
            with pytest.raises(EndOfStream):
                await wrapper.receive()

        server_thread.join()
        server_sock.close()

    @pytest.mark.parametrize(
        "force_tlsv12",
        [
            pytest.param(
                False,
                marks=[
                    pytest.mark.skipif(
                        not getattr(ssl, "HAS_TLSv1_3", False),
                        reason="No TLS 1.3 support",
                    )
                ],
            ),
            pytest.param(True),
        ],
        ids=["tlsv13", "tlsv12"],
    )
    async def test_send_eof_not_implemented(
        self, server_context: ssl.SSLContext, ca: CA, force_tlsv12: bool
    ) -> None:
        def serve_sync() -> None:
            conn, addr = server_sock.accept()
            conn.sendall(b"hello")
            conn.unwrap()
            conn.close()

        client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ca.configure_trust(client_context)
        if force_tlsv12:
            expected_pattern = r"send_eof\(\) requires at least TLSv1.3"
            client_context.maximum_version = ssl.TLSVersion.TLSv1_2
        else:
            expected_pattern = (
                r"send_eof\(\) has not yet been implemented for TLS streams"
            )

        server_sock = server_context.wrap_socket(
            socket.socket(), server_side=True, suppress_ragged_eofs=False
        )
        server_sock.settimeout(1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync, daemon=True)
        server_thread.start()

        stream = await connect_tcp(*server_sock.getsockname())
        async with await TLSStream.wrap(
            stream, hostname="localhost", ssl_context=client_context
        ) as wrapper:
            assert await wrapper.receive() == b"hello"
            with pytest.raises(NotImplementedError) as exc:
                await wrapper.send_eof()

            exc.match(expected_pattern)

        server_thread.join()
        server_sock.close()

    @pytest.mark.skipif(
        not hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"),
        reason="The ssl module does not have the OP_IGNORE_UNEXPECTED_EOF attribute",
    )
    async def test_default_context_ignore_unexpected_eof_flag_off(
        self, mocker: MockerFixture
    ) -> None:
        send1, receive1 = create_memory_object_stream[bytes]()
        client_stream = StapledObjectStream(send1, receive1)
        mocker.patch.object(TLSStream, "_call_sslobject_method")
        tls_stream = await TLSStream.wrap(client_stream)
        ssl_context = tls_stream.extra(TLSAttribute.ssl_object).context
        assert not ssl_context.options & ssl.OP_IGNORE_UNEXPECTED_EOF

        send1.close()
        receive1.close()


class TestTLSListener:
    async def test_handshake_fail(
        self, server_context: ssl.SSLContext, caplog: pytest.LogCaptureFixture
    ) -> None:
        def handler(stream: object) -> NoReturn:
            pytest.fail("This function should never be called in this scenario")

        exception = None

        class CustomTLSListener(TLSListener):
            @staticmethod
            async def handle_handshake_error(
                exc: BaseException, stream: AnyByteStream
            ) -> None:
                nonlocal exception
                await TLSListener.handle_handshake_error(exc, stream)

                # Regression test for #608
                assert len(caplog.records) == 1
                logged_exc_info = caplog.records[0].exc_info
                logged_exc = logged_exc_info[1] if logged_exc_info is not None else None
                assert logged_exc is exc

                assert isinstance(stream, SocketStream)
                exception = exc
                event.set()

        event = Event()
        listener = await create_tcp_listener(local_host="127.0.0.1")
        tls_listener = CustomTLSListener(listener, server_context)
        async with tls_listener, create_task_group() as tg:
            tg.start_soon(tls_listener.serve, handler)
            sock = socket.socket()
            sock.connect(listener.extra(SocketAttribute.local_address))
            sock.close()
            await event.wait()
            tg.cancel_scope.cancel()

        assert isinstance(exception, BrokenResourceError)

    async def test_extra_attributes(
        self, client_context: ssl.SSLContext, server_context: ssl.SSLContext, ca: CA
    ) -> None:
        def connect_sync(addr: tuple[str, int]) -> None:
            with socket.create_connection(addr) as plain_sock:
                plain_sock.settimeout(2)
                with client_context.wrap_socket(
                    plain_sock,
                    server_side=False,
                    server_hostname="localhost",
                    suppress_ragged_eofs=False,
                ) as conn:
                    conn.recv(1)
                    conn.unwrap()

        class CustomTLSListener(TLSListener):
            @staticmethod
            async def handle_handshake_error(
                exc: BaseException, stream: AnyByteStream
            ) -> None:
                await TLSListener.handle_handshake_error(exc, stream)
                pytest.fail("TLS handshake failed")

        async def handler(stream: TLSStream) -> None:
            async with stream:
                try:
                    assert stream.extra(TLSAttribute.alpn_protocol) == "h2"
                    assert isinstance(
                        stream.extra(TLSAttribute.channel_binding_tls_unique), bytes
                    )
                    assert isinstance(stream.extra(TLSAttribute.cipher), tuple)
                    assert isinstance(stream.extra(TLSAttribute.peer_certificate), dict)
                    assert isinstance(
                        stream.extra(TLSAttribute.peer_certificate_binary), bytes
                    )
                    assert stream.extra(TLSAttribute.server_side) is True
                    shared_ciphers = stream.extra(TLSAttribute.shared_ciphers)
                    assert isinstance(shared_ciphers, list)
                    assert len(shared_ciphers) > 1
                    assert isinstance(
                        stream.extra(TLSAttribute.ssl_object), ssl.SSLObject
                    )
                    assert stream.extra(TLSAttribute.standard_compatible) is True
                    assert stream.extra(TLSAttribute.tls_version).startswith("TLSv")
                finally:
                    event.set()
                    await stream.send(b"\x00")

        # Issue a client certificate and make the server trust it
        client_cert = ca.issue_cert("dummy-client")
        client_cert.configure_cert(client_context)
        ca.configure_trust(server_context)
        server_context.verify_mode = ssl.CERT_REQUIRED

        event = Event()
        server_context.set_alpn_protocols(["h2"])
        client_context.set_alpn_protocols(["h2"])
        listener = await create_tcp_listener(local_host="127.0.0.1")
        tls_listener = CustomTLSListener(listener, server_context)
        async with tls_listener, create_task_group() as tg:
            assert tls_listener.extra(TLSAttribute.standard_compatible) is True
            tg.start_soon(tls_listener.serve, handler)
            client_thread = Thread(
                target=connect_sync,
                args=[listener.extra(SocketAttribute.local_address)],
            )
            client_thread.start()
            await event.wait()
            await to_thread.run_sync(client_thread.join)
            tg.cancel_scope.cancel()
