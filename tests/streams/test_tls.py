import socket
import ssl
from contextlib import ExitStack
from threading import Thread
from typing import NoReturn

import pytest
from trustme import CA

from anyio import (
    BrokenResourceError, EndOfStream, Event, connect_tcp, create_task_group, create_tcp_listener)
from anyio.abc import AnyByteStream, SocketAttribute, SocketStream
from anyio.streams.tls import TLSAttribute, TLSListener, TLSStream

pytestmark = pytest.mark.anyio


class TestTLSStream:
    async def test_send_receive(self, server_context: ssl.SSLContext,
                                client_context: ssl.SSLContext) -> None:
        def serve_sync() -> None:
            conn, addr = server_sock.accept()
            conn.settimeout(1)
            data = conn.recv(10)
            conn.send(data[::-1])
            conn.close()

        server_sock = server_context.wrap_socket(socket.socket(), server_side=True,
                                                 suppress_ragged_eofs=False)
        server_sock.settimeout(1)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync)
        server_thread.start()

        async with await connect_tcp(*server_sock.getsockname()) as stream:
            wrapper = await TLSStream.wrap(stream, hostname='localhost',
                                           ssl_context=client_context)
            await wrapper.send(b'hello')
            response = await wrapper.receive()

        server_thread.join()
        server_sock.close()
        assert response == b'olleh'

    async def test_extra_attributes(self, server_context: ssl.SSLContext,
                                    client_context: ssl.SSLContext) -> None:
        def serve_sync() -> None:
            conn, addr = server_sock.accept()
            with conn:
                conn.settimeout(1)
                conn.recv(1)

        server_context.set_alpn_protocols(['h2'])
        client_context.set_alpn_protocols(['h2'])

        server_sock = server_context.wrap_socket(socket.socket(), server_side=True,
                                                 suppress_ragged_eofs=True)
        server_sock.settimeout(1)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync)
        server_thread.start()

        async with await connect_tcp(*server_sock.getsockname()) as stream:
            wrapper = await TLSStream.wrap(stream, hostname='localhost',
                                           ssl_context=client_context, standard_compatible=False)
            async with wrapper:
                for name, attribute in SocketAttribute.__dict__.items():
                    if not name.startswith('_'):
                        assert wrapper.extra(attribute) == stream.extra(attribute)

                assert wrapper.extra(TLSAttribute.alpn_protocol) == 'h2'
                assert isinstance(wrapper.extra(TLSAttribute.channel_binding_tls_unique), bytes)
                assert isinstance(wrapper.extra(TLSAttribute.cipher), tuple)
                assert isinstance(wrapper.extra(TLSAttribute.peer_certificate), dict)
                assert isinstance(wrapper.extra(TLSAttribute.peer_certificate_binary), bytes)
                assert wrapper.extra(TLSAttribute.server_side) is False
                assert isinstance(wrapper.extra(TLSAttribute.shared_ciphers), list)
                assert isinstance(wrapper.extra(TLSAttribute.ssl_object), ssl.SSLObject)
                assert wrapper.extra(TLSAttribute.standard_compatible) is False
                assert wrapper.extra(TLSAttribute.tls_version).startswith('TLSv')
                await wrapper.send(b'\x00')

        server_thread.join()
        server_sock.close()

    async def test_unwrap(self, server_context: ssl.SSLContext,
                          client_context: ssl.SSLContext) -> None:
        def serve_sync() -> None:
            conn, addr = server_sock.accept()
            conn.settimeout(1)
            conn.send(b'encrypted')
            unencrypted = conn.unwrap()
            unencrypted.send(b'unencrypted')
            unencrypted.close()

        server_sock = server_context.wrap_socket(socket.socket(), server_side=True,
                                                 suppress_ragged_eofs=False)
        server_sock.settimeout(1)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync)
        server_thread.start()

        async with await connect_tcp(*server_sock.getsockname()) as stream:
            wrapper = await TLSStream.wrap(stream, hostname='localhost',
                                           ssl_context=client_context)
            msg1 = await wrapper.receive()
            unwrapped_stream, msg2 = await wrapper.unwrap()
            if msg2 != b'unencrypted':
                msg2 += await unwrapped_stream.receive()

        server_thread.join()
        server_sock.close()
        assert msg1 == b'encrypted'
        assert msg2 == b'unencrypted'

    @pytest.mark.skipif(not ssl.HAS_ALPN, reason='ALPN support not available')
    async def test_alpn_negotiation(self, server_context: ssl.SSLContext,
                                    client_context: ssl.SSLContext) -> None:
        def serve_sync() -> None:
            conn, addr = server_sock.accept()
            conn.settimeout(1)
            selected_alpn_protocol = conn.selected_alpn_protocol()
            assert selected_alpn_protocol is not None
            conn.send(selected_alpn_protocol.encode())
            conn.close()

        server_context.set_alpn_protocols(['dummy1', 'dummy2'])
        client_context.set_alpn_protocols(['dummy2', 'dummy3'])

        server_sock = server_context.wrap_socket(socket.socket(), server_side=True,
                                                 suppress_ragged_eofs=False)
        server_sock.settimeout(1)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync)
        server_thread.start()

        async with await connect_tcp(*server_sock.getsockname()) as stream:
            wrapper = await TLSStream.wrap(stream, hostname='localhost',
                                           ssl_context=client_context)
            assert wrapper.extra(TLSAttribute.alpn_protocol) == 'dummy2'
            server_alpn_protocol = await wrapper.receive()

        server_thread.join()
        server_sock.close()
        assert server_alpn_protocol == b'dummy2'

    @pytest.mark.parametrize('server_compatible, client_compatible', [
        pytest.param(True, True, id='both_standard'),
        pytest.param(True, False, id='server_standard'),
        pytest.param(False, True, id='client_standard'),
        pytest.param(False, False, id='neither_standard')
    ])
    async def test_ragged_eofs(self, server_context: ssl.SSLContext,
                               client_context: ssl.SSLContext, server_compatible: bool,
                               client_compatible: bool) -> None:
        server_exc = None

        def serve_sync() -> None:
            nonlocal server_exc
            conn, addr = server_sock.accept()
            try:
                conn.settimeout(1)
                conn.sendall(b'hello')
                if server_compatible:
                    conn.unwrap()
            except BaseException as exc:
                server_exc = exc
            finally:
                conn.close()

        client_cm = ExitStack()
        if client_compatible and not server_compatible:
            client_cm = pytest.raises(BrokenResourceError)

        server_sock = server_context.wrap_socket(socket.socket(), server_side=True,
                                                 suppress_ragged_eofs=not server_compatible)
        server_sock.settimeout(1)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync, daemon=True)
        server_thread.start()

        stream = await connect_tcp(*server_sock.getsockname())
        wrapper = await TLSStream.wrap(stream, hostname='localhost', ssl_context=client_context,
                                       standard_compatible=client_compatible)
        with client_cm:
            assert await wrapper.receive() == b'hello'
            await wrapper.aclose()

        server_thread.join()
        server_sock.close()
        if not client_compatible and server_compatible:
            assert isinstance(server_exc, OSError)
            assert not isinstance(server_exc, socket.timeout)
        else:
            assert server_exc is None

    async def test_receive_send_after_eof(self, server_context: ssl.SSLContext,
                                          client_context: ssl.SSLContext) -> None:
        def serve_sync() -> None:
            conn, addr = server_sock.accept()
            conn.sendall(b'hello')
            conn.unwrap()
            conn.close()

        server_sock = server_context.wrap_socket(socket.socket(), server_side=True,
                                                 suppress_ragged_eofs=False)
        server_sock.settimeout(1)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync, daemon=True)
        server_thread.start()

        stream = await connect_tcp(*server_sock.getsockname())
        async with await TLSStream.wrap(stream, hostname='localhost',
                                        ssl_context=client_context) as wrapper:
            assert await wrapper.receive() == b'hello'
            with pytest.raises(EndOfStream):
                await wrapper.receive()

        server_thread.join()
        server_sock.close()

    @pytest.mark.parametrize('force_tlsv12', [
        pytest.param(False, marks=[pytest.mark.skipif(not getattr(ssl, 'HAS_TLSv1_3', False),
                                                      reason='No TLS 1.3 support')]),
        pytest.param(True)
    ], ids=['tlsv13', 'tlsv12'])
    async def test_send_eof_not_implemented(self, server_context: ssl.SSLContext,
                                            ca: CA, force_tlsv12: bool) -> None:
        def serve_sync() -> None:
            conn, addr = server_sock.accept()
            conn.sendall(b'hello')
            conn.unwrap()
            conn.close()

        client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ca.configure_trust(client_context)
        if force_tlsv12:
            expected_pattern = r'send_eof\(\) requires at least TLSv1.3'
            if hasattr(ssl, 'TLSVersion'):
                client_context.maximum_version = ssl.TLSVersion.TLSv1_2
            else:  # Python 3.6
                client_context.options |= ssl.OP_NO_TLSv1_3
        else:
            expected_pattern = r'send_eof\(\) has not yet been implemented for TLS streams'

        server_sock = server_context.wrap_socket(socket.socket(), server_side=True,
                                                 suppress_ragged_eofs=False)
        server_sock.settimeout(1)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync, daemon=True)
        server_thread.start()

        stream = await connect_tcp(*server_sock.getsockname())
        async with await TLSStream.wrap(stream, hostname='localhost',
                                        ssl_context=client_context) as wrapper:
            assert await wrapper.receive() == b'hello'
            with pytest.raises(NotImplementedError) as exc:
                await wrapper.send_eof()

            exc.match(expected_pattern)

        server_thread.join()
        server_sock.close()


class TestTLSListener:
    async def test_handshake_fail(self, server_context: ssl.SSLContext) -> None:
        def handler(stream: object) -> NoReturn:  # type: ignore[misc]
            pytest.fail('This function should never be called in this scenario')

        exception = None

        class CustomTLSListener(TLSListener):
            @staticmethod
            async def handle_handshake_error(exc: BaseException,
                                             stream: AnyByteStream) -> None:
                nonlocal exception
                await TLSListener.handle_handshake_error(exc, stream)
                assert isinstance(stream, SocketStream)
                exception = exc
                event.set()

        event = Event()
        listener = await create_tcp_listener(local_host='127.0.0.1')
        tls_listener = CustomTLSListener(listener, server_context)
        async with tls_listener, create_task_group() as tg:
            tg.start_soon(tls_listener.serve, handler)
            sock = socket.socket()
            sock.connect(listener.extra(SocketAttribute.local_address))
            sock.close()
            await event.wait()
            tg.cancel_scope.cancel()

        assert isinstance(exception, BrokenResourceError)
