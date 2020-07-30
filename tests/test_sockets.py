import platform
import socket
import sys
import time
from contextlib import suppress
from threading import Thread

import pytest

from anyio import (
    create_task_group, connect_tcp, create_udp_socket, connect_unix, create_unix_listener,
    create_tcp_listeners, wait_all_tasks_blocked, move_on_after, getaddrinfo, getnameinfo,
    serve_listeners, create_connected_udp_socket, connect_tcp_with_tls, create_event)
from anyio.exceptions import ExceptionGroup, BusyResourceError, ClosedResourceError

pytestmark = pytest.mark.anyio


@pytest.fixture
def fake_localhost_dns(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        # Make it return IPv4 addresses first so we can test the IPv6 preference
        results = real_getaddrinfo(*args, **kwargs)
        return sorted(results, key=lambda item: item[0])

    real_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr('socket.getaddrinfo', fake_getaddrinfo)


@pytest.fixture(params=[
    pytest.param(socket.AF_INET, id='ipv4'),
    pytest.param(socket.AF_INET6, id='ipv6',
                 marks=[pytest.mark.skipif(not socket.has_ipv6, reason='no IPv6 support')])
])
def family(request):
    return request.param


@pytest.fixture
def check_asyncio_bug(anyio_backend_name, family):
    if anyio_backend_name == 'asyncio' and sys.platform == 'win32' and family == socket.AF_INET6:
        import asyncio
        policy = asyncio.get_event_loop_policy()
        if policy.__class__.__name__ == 'WindowsProactorEventLoopPolicy':
            pytest.skip('Does not work due to a known bug (39148)')


class TestTCPStream:
    @pytest.fixture
    def server_sock(self, family):
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(1)
        sock.bind(('localhost', 0))
        sock.listen()
        yield sock
        sock.close()

    @pytest.fixture
    def server_addr(self, server_sock):
        return server_sock.getsockname()[:2]

    async def test_send_receive(self, server_sock, server_addr):
        async with await connect_tcp(*server_addr) as stream:
            client, _ = server_sock.accept()
            await stream.send(b'blah')
            request = client.recv(100)
            client.sendall(request[::-1])
            response = await stream.receive()
            client.close()

        assert response == b'halb'

    async def test_send_large_buffer(self, server_sock, server_addr):
        def serve():
            client, _ = server_sock.accept()
            client.sendall(buffer)
            client.close()

        buffer = b'\xff' * 1024 * 1024  # should exceed the maximum kernel send buffer size
        async with await connect_tcp(*server_addr) as stream:
            thread = Thread(target=serve, daemon=True)
            thread.start()
            response = b''
            while len(response) < len(buffer):
                response += await stream.receive()

        thread.join()
        assert response == buffer

    async def test_send_eof(self, server_sock, server_addr):
        def serve():
            client, _ = server_sock.accept()
            request = b''
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
            await stream.send(b'hello, ')
            await stream.send(b'world\n')
            await stream.send_eof()
            response = await stream.receive()

        thread.join()
        assert response == b'\ndlrow ,olleh'

    async def test_iterate(self, server_sock, server_addr):
        def serve():
            client, _ = server_sock.accept()
            client.sendall(b'bl')
            time.sleep(0.05)
            client.sendall(b'ah')
            client.close()

        thread = Thread(target=serve, daemon=True)
        thread.start()
        chunks = []
        async with await connect_tcp(*server_addr) as stream:
            async for chunk in stream:
                chunks.append(chunk)

        thread.join()
        assert chunks == [b'bl', b'ah']

    async def test_socket_options(self, family, server_addr):
        async with await connect_tcp(*server_addr) as stream:
            assert stream.family == family
            assert stream.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0
            stream.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 80000)
            assert stream.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) in (80000, 160000)

    @pytest.mark.skipif(not socket.has_ipv6, reason='IPv6 is not available')
    @pytest.mark.parametrize('local_addr, expected_client_addr', [
        pytest.param('', '::1', id='dualstack'),
        pytest.param('127.0.0.1', '127.0.0.1', id='ipv4'),
        pytest.param('::1', '::1', id='ipv6')
    ])
    async def test_happy_eyeballs(self, local_addr, expected_client_addr,
                                  fake_localhost_dns):
        def serve():
            nonlocal client_addr
            client, client_addr = server_sock.accept()
            client.close()

        client_addr = None, None
        family = socket.AF_INET if local_addr == '127.0.0.1' else socket.AF_INET6
        server_sock = socket.socket(family)
        server_sock.bind((local_addr, 0))
        server_sock.listen()
        port = server_sock.getsockname()[1]
        thread = Thread(target=serve, daemon=True)
        thread.start()

        async with await connect_tcp('localhost', port):
            pass

        thread.join()
        server_sock.close()
        assert client_addr[0] == expected_client_addr

    @pytest.mark.parametrize('target, exception_class', [
        pytest.param(
            'localhost', ExceptionGroup, id='multi',
            marks=[pytest.mark.skipif(not socket.has_ipv6, reason='IPv6 is not available')]
        ),
        pytest.param('127.0.0.1', ConnectionRefusedError, id='single')
    ])
    async def test_connection_refused(self, target, exception_class, fake_localhost_dns):
        dummy_socket = socket.socket(socket.AF_INET6)
        dummy_socket.bind(('::', 0))
        free_port = dummy_socket.getsockname()[1]
        dummy_socket.close()

        with pytest.raises(OSError) as exc:
            await connect_tcp(target, free_port)

        assert exc.match('All connection attempts failed')
        assert isinstance(exc.value.__cause__, exception_class)
        if exception_class is ExceptionGroup:
            for exc in exc.value.__cause__.exceptions:
                assert isinstance(exc, ConnectionRefusedError)

    async def test_receive_timeout(self, server_sock, server_addr):
        def serve():
            conn, _ = server_sock.accept()
            time.sleep(1)
            conn.close()

        thread = Thread(target=serve, daemon=True)
        thread.start()
        stream = await connect_tcp(*server_addr)
        start_time = time.monotonic()
        async with move_on_after(0.1):
            while time.monotonic() - start_time < 0.3:
                await stream.receive(1)

            pytest.fail('The timeout was not respected')

        # await stream.aclose()

    async def test_concurrent_send(self, server_addr):
        async def send_data():
            while True:
                await stream.send(b'\x00' * 4096)

        async with await connect_tcp(*server_addr) as stream:
            async with create_task_group() as tg:
                await tg.spawn(send_data)
                await wait_all_tasks_blocked()
                with pytest.raises(BusyResourceError) as exc:
                    await stream.send(b'foo')

                exc.match('already writing to')
                await tg.cancel_scope.cancel()

    async def test_concurrent_receive(self, server_addr):
        async with await connect_tcp(*server_addr) as client:
            async with create_task_group() as tg:
                await tg.spawn(client.receive)
                await wait_all_tasks_blocked()
                try:
                    with pytest.raises(BusyResourceError) as exc:
                        await client.receive()

                    exc.match('already reading from')
                finally:
                    await tg.cancel_scope.cancel()

    async def test_close_during_receive(self, server_addr):
        async def interrupt():
            await wait_all_tasks_blocked()
            await stream.aclose()

        async with await connect_tcp(*server_addr) as stream:
            async with create_task_group() as tg:
                await tg.spawn(interrupt)
                with pytest.raises(ClosedResourceError):
                    await stream.receive()

    async def test_receive_after_close(self, server_addr):
        stream = await connect_tcp(*server_addr)
        await stream.aclose()
        with pytest.raises(ClosedResourceError):
            await stream.receive()

    async def test_send_after_close(self, server_addr):
        stream = await connect_tcp(*server_addr)
        await stream.aclose()
        with pytest.raises(ClosedResourceError):
            await stream.send(b'foo')

    async def test_connect_tcp_with_tls(self, family, server_context, client_context):
        def serve():
            with suppress(socket.timeout):
                client, addr = server_sock.accept()
                data = client.recv(100)
                client.sendall(data[::-1])
                try:
                    client.unwrap()
                finally:
                    client.close()

        # The TLSStream tests are more comprehensive than this one!
        server_sock = server_context.wrap_socket(socket.socket(family), server_side=True,
                                                 suppress_ragged_eofs=False)
        server_sock.settimeout(1)
        server_sock.bind(('localhost', 0))
        server_sock.listen()
        server_addr = server_sock.getsockname()[:2]
        thread = Thread(target=serve, daemon=True)
        thread.start()
        async with await connect_tcp_with_tls(*server_addr, server_hostname='localhost',
                                              ssl_context=client_context) as stream:
            await stream.send(b'hello')
            response = await stream.receive()

        assert response == b'olleh'
        thread.join()
        server_sock.close()


class TestTCPListener:
    @pytest.mark.parametrize('family', [
        pytest.param(socket.AF_INET, id='ipv4'),
        pytest.param(socket.AF_INET6, id='ipv6',
                     marks=[pytest.mark.skipif(not socket.has_ipv6, reason='no IPv6 support')]),
        pytest.param(socket.AF_UNSPEC, id='both',
                     marks=[pytest.mark.skipif(not socket.has_ipv6, reason='no IPv6 support')])
    ])
    async def test_accept(self, family):
        listeners = await create_tcp_listeners(local_host='localhost', family=family)
        for listener in listeners:
            async with listener:
                client = socket.socket(listener.family)
                client.settimeout(1)
                client.connect(listener.local_address)
                stream = await listener.accept()
                client.sendall(b'blah')
                request = await stream.receive()
                await stream.send(request[::-1])
                assert client.recv(100) == b'halb'
                client.close()
                await stream.aclose()

    async def test_socket_options(self, family):
        listener = (await create_tcp_listeners(local_host='localhost', family=family))[0]
        async with listener:
            if sys.platform == 'win32':
                assert listener.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE) != 0
            else:
                assert listener.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) != 0

            listener.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 80000)
            assert listener.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) in (80000, 160000)

            client = socket.socket(listener.family)
            client.settimeout(1)
            client.connect(listener.local_address)

            async with await listener.accept() as stream:
                assert stream.family == listener.family
                assert stream.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0

            client.close()

    @pytest.mark.skipif(sys.platform == 'win32', reason='Not supported on Windows')
    async def test_reuse_port(self, family):
        listeners = await create_tcp_listeners(local_host='localhost', family=family,
                                               reuse_port=True)
        assert len(listeners) == 1

        listeners.extend(await create_tcp_listeners(
                local_host='localhost', local_port=listeners[0].local_address[1],
                family=family, reuse_port=True))
        assert len(listeners) == 2
        assert listeners[0].local_address == listeners[1].local_address
        for listener in listeners:
            await listener.aclose()


@pytest.mark.skipif(sys.platform == 'win32',
                    reason='UNIX sockets are not available on Windows')
class TestUNIXStream:
    @pytest.fixture
    def socket_path(self, tmp_path_factory):
        return tmp_path_factory.mktemp('unix').joinpath('socket')

    @pytest.fixture
    def server_sock(self, socket_path):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1)
        sock.bind(str(socket_path))
        sock.listen()
        yield sock
        sock.close()

    @pytest.mark.parametrize('as_path', [False, True], ids=['str', 'path'])
    async def test_send_receive(self, server_sock, socket_path, as_path):
        async with await connect_unix(socket_path) as stream:
            client, _ = server_sock.accept()
            await stream.send(b'blah')
            request = client.recv(100)
            client.sendall(request[::-1])
            response = await stream.receive()
            client.close()

        assert response == b'halb'

    async def test_send_large_buffer(self, server_sock, socket_path):
        def serve():
            client, _ = server_sock.accept()
            client.sendall(buffer)
            client.close()

        buffer = b'\xff' * 1024 * 1024  # should exceed the maximum kernel send buffer size
        async with await connect_unix(socket_path) as stream:
            thread = Thread(target=serve, daemon=True)
            thread.start()
            response = b''
            while len(response) < len(buffer):
                response += await stream.receive()

        thread.join()
        assert response == buffer

    async def test_send_eof(self, server_sock, socket_path):
        def serve():
            client, _ = server_sock.accept()
            request = b''
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
            await stream.send(b'hello, ')
            await stream.send(b'world\n')
            await stream.send_eof()
            response = await stream.receive()

        thread.join()
        assert response == b'\ndlrow ,olleh'

    async def test_iterate(self, server_sock, socket_path):
        def serve():
            client, _ = server_sock.accept()
            client.sendall(b'bl')
            time.sleep(0.05)
            client.sendall(b'ah')
            client.close()

        thread = Thread(target=serve, daemon=True)
        thread.start()
        chunks = []
        async with await connect_unix(socket_path) as stream:
            async for chunk in stream:
                chunks.append(chunk)

        thread.join()
        assert chunks == [b'bl', b'ah']

    async def test_socket_options(self, server_sock, socket_path):
        async with await connect_unix(socket_path) as stream:
            assert stream.family == socket.AddressFamily.AF_UNIX
            stream.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 80000)
            assert stream.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) in (80000, 160000)

    async def test_concurrent_send(self, server_sock, socket_path):
        async def send_data():
            while True:
                await client.send(b'\x00' * 4096)

        async with await connect_unix(socket_path) as client:
            async with create_task_group() as tg:
                await tg.spawn(send_data)
                await wait_all_tasks_blocked()
                with pytest.raises(BusyResourceError) as exc:
                    await client.send(b'foo')

                exc.match('already writing to')
                await tg.cancel_scope.cancel()

    async def test_concurrent_receive(self, server_sock, socket_path):
        async with await connect_unix(socket_path) as client:
            async with create_task_group() as tg:
                await tg.spawn(client.receive)
                await wait_all_tasks_blocked()
                try:
                    with pytest.raises(BusyResourceError) as exc:
                        await client.receive()

                    exc.match('already reading from')
                finally:
                    await tg.cancel_scope.cancel()

    async def test_close_during_receive(self, server_sock, socket_path):
        async def interrupt():
            await wait_all_tasks_blocked()
            await stream.aclose()

        async with await connect_unix(socket_path) as stream:
            async with create_task_group() as tg:
                await tg.spawn(interrupt)
                with pytest.raises(ClosedResourceError):
                    await stream.receive()

    async def test_receive_after_close(self, server_sock, socket_path):
        stream = await connect_unix(socket_path)
        await stream.aclose()
        with pytest.raises(ClosedResourceError):
            await stream.receive()

    async def test_send_after_close(self, server_sock, socket_path):
        stream = await connect_unix(socket_path)
        await stream.aclose()
        with pytest.raises(ClosedResourceError):
            await stream.send(b'foo')


@pytest.mark.skipif(sys.platform == 'win32',
                    reason='UNIX sockets are not available on Windows')
class TestUNIXListener:
    @pytest.fixture
    def socket_path(self, tmp_path_factory):
        return tmp_path_factory.mktemp('unix').joinpath('socket')

    @pytest.mark.parametrize('as_path', [False, True], ids=['str', 'path'])
    async def test_accept(self, socket_path, as_path):
        if not as_path:
            socket_path = str(socket_path)

        async with await create_unix_listener(socket_path) as listener:
            client = socket.socket(socket.AF_UNIX)
            client.settimeout(1)
            client.connect(str(socket_path))
            stream = await listener.accept()
            client.sendall(b'blah')
            request = await stream.receive()
            await stream.send(request[::-1])
            assert client.recv(100) == b'halb'
            client.close()
            await stream.aclose()

    async def test_socket_options(self, socket_path):
        async with await create_unix_listener(socket_path) as listener:
            assert listener.family == socket.AddressFamily.AF_UNIX
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 80000)
            assert listener.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) in (80000, 160000)

            client = socket.socket(listener.family)
            client.settimeout(1)
            client.connect(listener.local_address)

            async with await listener.accept() as stream:
                assert stream.family == listener.family

            client.close()


async def test_serve_listeners(tmp_path_factory):
    async def handle(stream):
        client_addresses.append(stream.remote_address)
        await event.set()
        await stream.aclose()

    client_addresses = []
    listeners = await create_tcp_listeners(local_host='localhost')
    if sys.platform != 'win32':
        socket_path = tmp_path_factory.mktemp('unix').joinpath('socket')
        listeners.append(await create_unix_listener(socket_path))

    expected_addresses = []
    async with create_task_group() as tg:
        await tg.spawn(serve_listeners, handle, listeners)
        for listener in listeners:
            event = create_event()
            if sys.platform != 'win32' and listener.family == socket.AddressFamily.AF_UNIX:
                stream = await connect_unix(listener.local_address)
            else:
                stream = await connect_tcp(*listener.local_address[:2])

            expected_addresses.append(stream.local_address)
            await event.wait()
            await stream.aclose()

        await tg.cancel_scope.cancel()

    assert client_addresses == expected_addresses


@pytest.mark.usefixtures('check_asyncio_bug')
class TestUDPSocket:
    async def test_send_receive(self, family):
        async with await create_udp_socket(local_host='localhost', family=family) as sock:
            await sock.sendto(b'blah', *sock.local_address[:2])
            request, addr = await sock.receive()
            assert request == b'blah'
            assert addr == sock.local_address

            await sock.sendto(b'halb', *sock.local_address[:2])
            response, addr = await sock.receive()
            assert response == b'halb'
            assert addr == sock.local_address

    async def test_iterate(self, family):
        async def serve():
            async for packet, addr in server:
                await server.send((packet[::-1], addr[:2]))

        async with await create_udp_socket(family=family, local_host='localhost') as server:
            host, port = server.local_address[:2]
            async with await create_udp_socket(family=family, local_host='localhost') as client:
                async with create_task_group() as tg:
                    await tg.spawn(serve)
                    await client.sendto(b'FOOBAR', host, port)
                    assert await client.receive() == (b'RABOOF', server.local_address)
                    await client.sendto(b'123456', host, port)
                    assert await client.receive() == (b'654321', server.local_address)
                    await tg.cancel_scope.cancel()

    async def test_socket_options(self, family):
        async with await create_udp_socket(family=family, local_host='localhost') as udp:
            assert udp.family == family
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 80000)
            assert udp.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) in (80000, 160000)

    @pytest.mark.skipif(sys.platform == 'win32', reason='Not supported on Windows')
    async def test_reuse_port(self, family):
        async with await create_udp_socket(family=family, local_host='localhost',
                                           reuse_port=True) as udp:
            port = udp.local_address[1]
            assert port != 0
            async with await create_udp_socket(family=family, local_host='localhost',
                                               local_port=port, reuse_port=True) as udp2:
                assert port == udp2.local_address[1]

    async def test_concurrent_receive(self):
        async with await create_udp_socket(family=socket.AF_INET, local_host='localhost') as udp:
            async with create_task_group() as tg:
                await tg.spawn(udp.receive)
                await wait_all_tasks_blocked()
                try:
                    with pytest.raises(BusyResourceError) as exc:
                        await udp.receive()

                    exc.match('already reading from')
                finally:
                    await tg.cancel_scope.cancel()

    async def test_close_during_receive(self):
        async def close_when_blocked():
            await wait_all_tasks_blocked()
            await udp.aclose()

        async with await create_udp_socket(family=socket.AF_INET, local_host='localhost') as udp:
            async with create_task_group() as tg:
                await tg.spawn(close_when_blocked)
                with pytest.raises(ClosedResourceError):
                    await udp.receive()

    async def test_receive_after_close(self):
        udp = await create_udp_socket(family=socket.AF_INET, local_host='localhost')
        await udp.aclose()
        with pytest.raises(ClosedResourceError):
            await udp.receive()

    async def test_send_after_close(self):
        udp = await create_udp_socket(family=socket.AF_INET, local_host='localhost')
        host, port = udp.local_address[:2]
        await udp.aclose()
        with pytest.raises(ClosedResourceError):
            await udp.sendto(b'foo', host, port)


@pytest.mark.usefixtures('check_asyncio_bug')
class TestConnectedUDPSocket:
    async def test_send_receive(self, family):
        async with await create_connected_udp_socket(
                'localhost', 5000, local_port=5000, local_host='localhost',
                family=family) as udp:
            await udp.send(b'blah')
            request = await udp.receive()
            assert request == b'blah'

            await udp.send(b'halb')
            response = await udp.receive()
            assert response == b'halb'

    async def test_iterate(self, family):
        async def serve():
            async for packet in udp2:
                await udp2.send(packet[::-1])

        async with await create_udp_socket(family=family, local_host='localhost') as udp1:
            host, port = udp1.local_address[:2]
            async with await create_connected_udp_socket(host, port) as udp2:
                host, port = udp2.local_address[:2]
                async with create_task_group() as tg:
                    await tg.spawn(serve)
                    await udp1.sendto(b'FOOBAR', host, port)
                    assert await udp1.receive() == (b'RABOOF', udp2.local_address)
                    await udp1.sendto(b'123456', host, port)
                    assert await udp1.receive() == (b'654321', udp2.local_address)
                    await tg.cancel_scope.cancel()

    async def test_socket_options(self, family):
        async with await create_connected_udp_socket(
                'localhost', 5000, family=family, local_host='localhost') as udp:
            assert udp.family == family
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 80000)
            assert udp.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) in (80000, 160000)

    @pytest.mark.skipif(sys.platform == 'win32', reason='Not supported on Windows')
    async def test_reuse_port(self, family):
        async with await create_connected_udp_socket(
                'localhost', 6000, family=family, local_host='localhost', reuse_port=True) as udp:
            port = udp.local_address[1]
            assert port != 0
            async with await create_connected_udp_socket(
                    'localhost', 6001, family=family, local_host='localhost', local_port=port,
                    reuse_port=True) as udp2:
                assert port == udp2.local_address[1]

    async def test_concurrent_receive(self):
        async with await create_connected_udp_socket(
                'localhost', 5000, local_port=5000, local_host='localhost',
                family=socket.AF_INET) as udp:
            async with create_task_group() as tg:
                await tg.spawn(udp.receive)
                await wait_all_tasks_blocked()
                try:
                    with pytest.raises(BusyResourceError) as exc:
                        await udp.receive()

                    exc.match('already reading from')
                finally:
                    await tg.cancel_scope.cancel()

    async def test_close_during_receive(self):
        async def close_when_blocked():
            await wait_all_tasks_blocked()
            await udp.aclose()

        async with await create_connected_udp_socket(
                'localhost', 5000, local_port=5000, local_host='localhost',
                family=socket.AF_INET) as udp:
            async with create_task_group() as tg:
                await tg.spawn(close_when_blocked)
                with pytest.raises(ClosedResourceError):
                    await udp.receive()

    async def test_receive_after_close(self, family):
        udp = await create_connected_udp_socket('localhost', 5000, local_port=5000,
                                                local_host='localhost', family=family)
        await udp.aclose()
        with pytest.raises(ClosedResourceError):
            await udp.receive()

    async def test_send_after_close(self, family):
        udp = await create_connected_udp_socket('localhost', 5000, local_port=5000,
                                                local_host='localhost', family=family)
        await udp.aclose()
        with pytest.raises(ClosedResourceError):
            await udp.send(b'foo')


async def test_getaddrinfo():
    # IDNA 2003 gets this wrong
    correct = await getaddrinfo('faß.de', 0)
    wrong = await getaddrinfo('fass.de', 0)
    assert correct != wrong


@pytest.mark.parametrize('sock_type', [socket.SOCK_STREAM, socket.SocketKind.SOCK_STREAM])
async def test_getaddrinfo_ipv6addr(sock_type):
    # IDNA trips up over raw IPv6 addresses
    proto = 0 if platform.system() == 'Windows' else 6
    assert await getaddrinfo('::1', 0, type=sock_type) == [
        (socket.AddressFamily.AF_INET6, socket.SocketKind.SOCK_STREAM, proto, '',
         ('::1', 0, 0, 0))
    ]


async def test_getnameinfo():
    expected_result = socket.getnameinfo(('127.0.0.1', 6666), 0)
    result = await getnameinfo(('127.0.0.1', 6666))
    assert result == expected_result
