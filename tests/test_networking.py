import socket
import ssl
import sys
from pathlib import Path

import pytest

from anyio import (
    create_task_group, connect_tcp, create_udp_socket, connect_unix, create_unix_server,
    create_tcp_server, wait_all_tasks_blocked)
from anyio.exceptions import (
    IncompleteRead, DelimiterNotFound, ClosedResourceError,
    ResourceBusyError)


class TestTCPStream:
    @pytest.mark.anyio
    async def test_receive_some(self):
        async def server():
            async with await stream_server.accept() as stream:
                assert stream.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0
                command = await stream.receive_some(100)
                await stream.send_all(command[::-1])

        async with create_task_group() as tg:
            async with await create_tcp_server(interface='localhost') as stream_server:
                await tg.spawn(server)
                async with await connect_tcp('localhost', stream_server.port) as client:
                    assert client.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0
                    await client.send_all(b'blah')
                    response = await client.receive_some(100)

        assert response == b'halb'

    @pytest.mark.anyio
    async def test_receive_some_from_cache(self):
        async def server():
            async with await stream_server.accept() as stream:
                await stream.receive_until(b'a', 10)
                request = await stream.receive_some(1)
                await stream.send_all(request + b'\n')

        received = None
        async with create_task_group() as tg:
            async with await create_tcp_server(interface='localhost') as stream_server:
                await tg.spawn(server)
                async with await connect_tcp('localhost', stream_server.port) as client:
                    await client.send_all(b'abc')
                    received = await client.receive_until(b'\n', 3)

        assert received == b'b'

    @pytest.mark.parametrize('method_name, params', [
        ('receive_until', [b'\n', 100]),
        ('receive_exactly', [5])
    ], ids=['read_until', 'read_exactly'])
    @pytest.mark.anyio
    async def test_read_partial(self, method_name, params):
        async def server():
            async with await stream_server.accept() as stream:
                method = getattr(stream, method_name)
                line1 = await method(*params)
                line2 = await method(*params)
                await stream.send_all(line1.strip() + line2.strip())

        async with create_task_group() as tg:
            async with await create_tcp_server(interface='localhost') as stream_server:
                await tg.spawn(server)
                async with await connect_tcp('localhost', stream_server.port) as client:
                    await client.send_all(b'bla')
                    await client.send_all(b'h\nb')
                    await client.send_all(b'leh\n')
                    response = await client.receive_some(100)

        assert response == b'blahbleh'

    @pytest.mark.anyio
    async def test_send_large_buffer(self):
        async def server():
            async with await stream_server.accept() as stream:
                await stream.send_all(buffer)

        buffer = b'\xff' * 1024 * 1024  # should exceed the maximum kernel send buffer size
        async with create_task_group() as tg:
            async with await create_tcp_server(interface='localhost') as stream_server:
                await tg.spawn(server)
                async with await connect_tcp('localhost', stream_server.port) as client:
                    response = await client.receive_exactly(len(buffer))
                    with pytest.raises(IncompleteRead):
                        await client.receive_exactly(1)

        assert response == buffer

    @pytest.mark.parametrize('method_name, params', [
        ('receive_until', [b'\n', 100]),
        ('receive_exactly', [5])
    ], ids=['read_until', 'read_exactly'])
    @pytest.mark.anyio
    async def test_incomplete_read(self, method_name, params):
        async def server():
            async with await stream_server.accept() as stream:
                await stream.send_all(b'bla')

        async with create_task_group() as tg:
            async with await create_tcp_server(interface='localhost') as stream_server:
                await tg.spawn(server)
                async with await connect_tcp('localhost', stream_server.port) as client:
                    method = getattr(client, method_name)
                    with pytest.raises(IncompleteRead):
                        await method(*params)

    @pytest.mark.anyio
    async def test_delimiter_not_found(self):
        async def server():
            async with await stream_server.accept() as stream:
                await stream.send_all(b'blah\n')

        async with create_task_group() as tg:
            async with await create_tcp_server(interface='localhost') as stream_server:
                await tg.spawn(server)
                async with await connect_tcp('localhost', stream_server.port) as client:
                    with pytest.raises(DelimiterNotFound) as exc:
                        await client.receive_until(b'\n', 3)

                    assert exc.match(' first 3 bytes$')

    @pytest.mark.anyio
    async def test_receive_chunks(self):
        async def server():
            async with await stream_server.accept() as stream:
                async for chunk in stream.receive_chunks(2):
                    chunks.append(chunk)

        chunks = []
        async with await create_tcp_server(interface='localhost') as stream_server:
            async with create_task_group() as tg:
                await tg.spawn(server)
                async with await connect_tcp('localhost', stream_server.port) as client:
                    await client.send_all(b'blah')

        assert chunks == [b'bl', b'ah']

    @pytest.mark.anyio
    async def test_buffer(self):
        async def server():
            async with await stream_server.accept() as stream:
                chunks.append(await stream.receive_until(b'\n', 10))
                chunks.append(await stream.receive_exactly(4))
                chunks.append(await stream.receive_exactly(2))

        chunks = []
        async with await create_tcp_server(interface='localhost') as stream_server:
            async with create_task_group() as tg:
                await tg.spawn(server)
                async with await connect_tcp('localhost', stream_server.port) as client:
                    await client.send_all(b'blah\nfoobar')

        assert chunks == [b'blah', b'foob', b'ar']

    @pytest.mark.anyio
    async def test_receive_delimited_chunks(self):
        async def server():
            async with await stream_server.accept() as stream:
                async for chunk in stream.receive_delimited_chunks(b'\r\n', 8):
                    chunks.append(chunk)

        chunks = []
        async with await create_tcp_server(interface='localhost') as stream_server:
            async with create_task_group() as tg:
                await tg.spawn(server)
                async with await connect_tcp('localhost', stream_server.port) as client:
                    for chunk in (b'bl', b'ah', b'\r', b'\nfoo', b'bar\r\n'):
                        await client.send_all(chunk)

        assert chunks == [b'blah', b'foobar']

    @pytest.mark.anyio
    async def test_accept_connections(self):
        async def handle_client(stream):
            async with stream:
                line = await stream.receive_until(b'\n', 10)
                lines.add(line)

            if len(lines) == 2:
                await stream_server.close()

        async def server():
            async for stream in stream_server.accept_connections():
                await tg.spawn(handle_client, stream)

        lines = set()
        async with await create_tcp_server(interface='localhost') as stream_server:
            async with create_task_group() as tg:
                await tg.spawn(server)

                async with await connect_tcp('localhost', stream_server.port) as client:
                    await client.send_all(b'client1\n')

                async with await connect_tcp('localhost', stream_server.port) as client:
                    await client.send_all(b'client2\n')

        assert lines == {b'client1', b'client2'}

    @pytest.mark.anyio
    async def test_socket_options(self):
        async with await create_tcp_server(interface='localhost') as stream_server:
            stream_server.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 80000)
            assert stream_server.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) in (80000, 160000)
            async with await connect_tcp('localhost', stream_server.port) as client:
                client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 80000)
                assert client.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) in (80000, 160000)

    @pytest.mark.anyio
    async def test_concurrent_write(self):
        async def send_data():
            while True:
                await client.send_all(b'\x00' * 1024000)

        async with await create_tcp_server(interface='localhost') as stream_server:
            async with await connect_tcp('localhost', stream_server.port) as client:
                async with create_task_group() as tg:
                    await tg.spawn(send_data)
                    await wait_all_tasks_blocked()
                    try:
                        with pytest.raises(ResourceBusyError) as exc:
                            await client.send_all(b'foo')

                        exc.match('already writing to')
                    finally:
                        await tg.cancel_scope.cancel()

    @pytest.mark.anyio
    async def test_concurrent_read(self):
        async def receive_data():
            await client.receive_exactly(1)

        async with await create_tcp_server(interface='localhost') as stream_server:
            async with await connect_tcp('localhost', stream_server.port) as client:
                async with create_task_group() as tg:
                    await tg.spawn(receive_data)
                    await wait_all_tasks_blocked()
                    try:
                        with pytest.raises(ResourceBusyError) as exc:
                            await client.receive_exactly(1)

                        exc.match('already reading from')
                    finally:
                        await tg.cancel_scope.cancel()


class TestUNIXStream:
    @pytest.mark.skipif(sys.platform == 'win32',
                        reason='UNIX sockets are not available on Windows')
    @pytest.mark.parametrize('as_path', [False])
    @pytest.mark.anyio
    async def test_connect_unix(self, tmp_path_factory, as_path):
        async def server():
            async with await stream_server.accept() as stream:
                command = await stream.receive_some(100)
                await stream.send_all(command[::-1])

        async with create_task_group() as tg:
            path = str(tmp_path_factory.mktemp('unix').joinpath('socket'))
            if as_path:
                path = Path(path)

            async with await create_unix_server(path) as stream_server:
                await tg.spawn(server)
                async with await connect_unix(path) as client:
                    await client.send_all(b'blah')
                    response = await client.receive_some(100)

        assert response == b'halb'


class TestTLSStream:
    @pytest.fixture
    def server_context(self):
        server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        server_context.load_cert_chain(certfile=str(Path(__file__).with_name('cert.pem')),
                                       keyfile=str(Path(__file__).with_name('key.pem')))
        return server_context

    @pytest.fixture
    def client_context(self):
        client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        client_context.load_verify_locations(cafile=str(Path(__file__).with_name('cert.pem')))
        return client_context

    @pytest.mark.anyio
    async def test_handshake_on_connect(self, server_context, client_context):
        async def server():
            nonlocal server_binding
            async with await stream_server.accept() as stream:
                assert stream.server_side
                assert stream.server_hostname is None
                assert stream.tls_version.startswith('TLSv')
                assert stream.cipher in stream.shared_ciphers
                server_binding = stream.get_channel_binding()

                command = await stream.receive_some(100)
                await stream.send_all(command[::-1])

        server_binding = None
        async with create_task_group() as tg:
            async with await create_tcp_server(
                    interface='localhost', ssl_context=server_context) as stream_server:
                await tg.spawn(server)
                async with await connect_tcp(
                        'localhost', stream_server.port, ssl_context=client_context,
                        autostart_tls=True) as client:
                    assert not client.server_side
                    assert client.server_hostname == 'localhost'
                    assert client.tls_version.startswith('TLSv')
                    assert client.cipher in client.shared_ciphers
                    client_binding = client.get_channel_binding()

                    await client.send_all(b'blah')
                    response = await client.receive_some(100)

        assert response == b'halb'
        assert client_binding == server_binding
        assert isinstance(client_binding, bytes)

    @pytest.mark.skipif(not ssl.HAS_ALPN, reason='ALPN support not available')
    @pytest.mark.anyio
    async def test_alpn_negotiation(self, server_context, client_context):
        async def server():
            async with await stream_server.accept() as stream:
                assert stream.alpn_protocol == 'dummy2'

        client_context.set_alpn_protocols(['dummy1', 'dummy2'])
        server_context.set_alpn_protocols(['dummy2', 'dummy3'])
        async with await create_tcp_server(interface='localhost',
                                           ssl_context=server_context) as stream_server:
            async with create_task_group() as tg:
                await tg.spawn(server)
                async with await connect_tcp(
                        'localhost', stream_server.port, ssl_context=client_context,
                        autostart_tls=True) as client:
                    assert client.alpn_protocol == 'dummy2'

    @pytest.mark.anyio
    async def test_manual_handshake(self, server_context, client_context):
        async def server():
            async with await stream_server.accept() as stream:
                assert stream.tls_version is None

                while True:
                    command = await stream.receive_exactly(5)
                    if command == b'START':
                        await stream.start_tls()
                        assert stream.tls_version.startswith('TLSv')
                    elif command == b'CLOSE':
                        break

        async with await create_tcp_server(interface='localhost', ssl_context=server_context,
                                           autostart_tls=False) as stream_server:
            async with create_task_group() as tg:
                await tg.spawn(server)
                async with await connect_tcp('localhost', stream_server.port,
                                             ssl_context=client_context) as client:
                    assert client.tls_version is None

                    await client.send_all(b'START')  # arbitrary string
                    await client.start_tls()

                    assert client.tls_version.startswith('TLSv')
                    await client.send_all(b'CLOSE')  # arbitrary string

    @pytest.mark.anyio
    async def test_buffer(self, server_context, client_context):
        async def server():
            async with await stream_server.accept() as stream:
                chunks.append(await stream.receive_until(b'\n', 10))
                chunks.append(await stream.receive_exactly(4))
                chunks.append(await stream.receive_exactly(2))

        chunks = []
        async with await create_tcp_server(interface='localhost',
                                           ssl_context=server_context) as stream_server:
            async with create_task_group() as tg:
                await tg.spawn(server)
                async with await connect_tcp(
                        'localhost', stream_server.port, ssl_context=client_context,
                        autostart_tls=True) as client:
                    await client.send_all(b'blah\nfoobar')

        assert chunks == [b'blah', b'foob', b'ar']

    @pytest.mark.parametrize('server_compatible, client_compatible, exc_class', [
        (True, True, IncompleteRead),
        (True, False, ssl.SSLEOFError),
        (False, True, IncompleteRead),
        (False, False, IncompleteRead)
    ], ids=['both_standard', 'server_standard', 'client_standard', 'neither_standard'])
    @pytest.mark.anyio
    async def test_ragged_eofs(self, server_context, client_context, server_compatible,
                               client_compatible, exc_class):
        async def server():
            async with await stream_server.accept() as stream:
                chunks.append(await stream.receive_exactly(2))
                with pytest.raises(exc_class):
                    await stream.receive_exactly(2)

        chunks = []
        async with await create_tcp_server(
                interface='localhost', ssl_context=server_context,
                tls_standard_compatible=server_compatible) as stream_server:
            async with create_task_group() as tg:
                await tg.spawn(server)
                async with await connect_tcp(
                        'localhost', stream_server.port, ssl_context=client_context,
                        autostart_tls=True, tls_standard_compatible=client_compatible) as client:
                    await client.send_all(b'bl')

        assert chunks == [b'bl']


class TestUDPSocket:
    @pytest.mark.anyio
    async def test_udp(self):
        async with await create_udp_socket(port=5000, interface='localhost',
                                           target_port=5000, target_host='localhost') as socket:
            await socket.send(b'blah')
            request, addr = await socket.receive(100)
            assert request == b'blah'
            assert addr == ('127.0.0.1', 5000)

            await socket.send(b'halb')
            response, addr = await socket.receive(100)
            assert response == b'halb'
            assert addr == ('127.0.0.1', 5000)

    @pytest.mark.anyio
    async def test_udp_noconnect(self):
        async with await create_udp_socket(interface='localhost') as socket:
            await socket.send(b'blah', 'localhost', socket.port)
            request, addr = await socket.receive(100)
            assert request == b'blah'
            assert addr == ('127.0.0.1', socket.port)

            await socket.send(b'halb', 'localhost', socket.port)
            response, addr = await socket.receive(100)
            assert response == b'halb'
            assert addr == ('127.0.0.1', socket.port)

    @pytest.mark.anyio
    async def test_udp_close_socket_from_other_task(self):
        async with create_task_group() as tg:
            async with await create_udp_socket(interface='127.0.0.1') as udp:
                await tg.spawn(udp.close)
                with pytest.raises(ClosedResourceError):
                    await udp.receive(100)

    @pytest.mark.anyio
    async def test_udp_receive_packets(self):
        async def serve():
            async for packet, addr in server.receive_packets(10000):
                await server.send(packet[::-1], *addr)

        async with await create_udp_socket(interface='127.0.0.1') as server:
            async with await create_udp_socket(target_host='127.0.0.1',
                                               target_port=server.port) as client:
                async with create_task_group() as tg:
                    await tg.spawn(serve)
                    await client.send(b'FOOBAR')
                    assert await client.receive(100) == (b'RABOOF', ('127.0.0.1', server.port))
                    await client.send(b'123456')
                    assert await client.receive(100) == (b'654321', ('127.0.0.1', server.port))
                    await tg.cancel_scope.cancel()

    @pytest.mark.anyio
    async def test_socket_options(self):
        async with await create_udp_socket(interface='127.0.0.1') as udp:
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 80000)
            assert udp.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) in (80000, 160000)
