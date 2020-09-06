import socket
import ssl
from contextlib import ExitStack
from threading import Thread

import pytest

from anyio import BrokenResourceError, connect_tcp
from anyio.streams.tls import TLSAttribute, TLSStream


class TestTLSStream:
    @pytest.mark.anyio
    async def test_send_receive(self, server_context, client_context):
        def serve_sync():
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

    @pytest.mark.anyio
    async def test_unwrap(self, server_context, client_context):
        def serve_sync():
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
            stream, msg2 = await wrapper.unwrap()
            if msg2 != b'unencrypted':
                msg2 += await stream.receive()

        server_thread.join()
        server_sock.close()
        assert msg1 == b'encrypted'
        assert msg2 == b'unencrypted'

    @pytest.mark.skipif(not ssl.HAS_ALPN, reason='ALPN support not available')
    @pytest.mark.anyio
    async def test_alpn_negotiation(self, server_context, client_context):
        def serve_sync():
            conn, addr = server_sock.accept()
            conn.settimeout(1)
            conn.send(conn.selected_alpn_protocol().encode())
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
            server_alpn_protocol = await wrapper.receive()

        server_thread.join()
        server_sock.close()
        assert wrapper.extra(TLSAttribute.alpn_protocol) == 'dummy2'
        assert server_alpn_protocol == b'dummy2'

    @pytest.mark.parametrize('server_compatible, client_compatible', [
        pytest.param(True, True, id='both_standard'),
        pytest.param(True, False, id='server_standard'),
        pytest.param(False, True, id='client_standard'),
        pytest.param(False, False, id='neither_standard')
    ])
    @pytest.mark.anyio
    async def test_ragged_eofs(self, server_context, client_context, server_compatible,
                               client_compatible):
        def serve_sync():
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

        server_exc = None
        server_sock = server_context.wrap_socket(socket.socket(), server_side=True,
                                                 suppress_ragged_eofs=not server_compatible)
        server_sock.settimeout(1)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen()
        server_thread = Thread(target=serve_sync)
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
