import pytest

from hyperio import create_socket, create_task_group


@pytest.mark.hyperio
async def test_listen_connect():
    async def server():
        connection, addr = await server_sock.accept()
        async with connection:
            command = await connection.recv(100)
            await connection.send(command[::-1])

    async with create_socket() as server_sock, create_task_group() as tg:
        await server_sock.bind(('127.0.0.1', 0))
        server_sock.listen(5)
        address = server_sock.getsockname()
        await tg.spawn(server)
        async with create_socket() as client:
            await client.connect(address)
            await client.send(b'blah')
            response = await client.recv(100)

    assert response == b'halb'
