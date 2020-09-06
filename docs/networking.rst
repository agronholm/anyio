Using sockets and streams
=========================

.. py:currentmodule:: anyio

Networking capabilities are arguably the most important part of any asynchronous library.
AnyIO contains its own high level implementation of networking on top of low level primitives
offered by each of its supported backends.

Currently AnyIO offers the following networking functionality:

* TCP sockets (client + server)
* UNIX domain sockets (client + server)
* UDP sockets

More exotic forms of networking such as raw sockets and SCTP are currently not supported.

.. warning:: Unlike the standard BSD sockets interface and most other networking libraries, AnyIO
    (from 2.0 onwards) signals the end of any stream by raising the
    :exc:`~EndOfStream` exception instead of returning an empty bytes object.

Working with TCP sockets
------------------------

TCP (Transmission Control Protocol) is the most commonly used protocol on the Internet. It allows
one to connect to a port on a remote host and send and receive data in a reliable manner.

To connect to a listening TCP socket somewhere, you can use :func:`~connect_tcp`::

    from anyio import connect_tcp, run


    async def main():
        async with await connect_tcp('hostname', 1234) as client:
            await client.send(b'Client\n')
            response = await client.receive()
            print(response)

    run(main)

As a convenience, you can also use :func:`~connect_tcp` to establish a TLS session with the
peer after connection, by passing ``tls=True`` or by passing a nonempty value for either
``ssl_context`` or ``tls_hostname``.

To receive incoming TCP connections, you first create a TCP listener with
:func:`create_tcp_listener` and call :meth:`~.abc.Listener.serve` on it::

    from anyio import create_tcp_listener, run


    async def handle(client):
        async with client:
            name = await client.receive(1024)
            await client.send(b'Hello, %s\n' % name)


    async def main():
        listener = await create_tcp_listener(local_port=1234)
        await listener.serve(handle)

    run(main)

See the section on :ref:`TLS` for more information.

Working with UNIX sockets
-------------------------

UNIX domain sockets are a form of interprocess communication on UNIX-like operating systems.
They cannot be used to connect to remote hosts and do not work on Windows.

The API for UNIX domain sockets is much like the one for TCP sockets, except that instead of
host/port combinations, you use file system paths.

This is what the client from the TCP example looks like when converted to use UNIX sockets::

    from anyio import connect_unix, run


    async def main():
        async with await connect_unix('/tmp/mysock') as client:
            await client.send(b'Client\n')
            response = await client.receive(1024)
            print(response)

    run(main)

And the listener::

    from anyio import create_unix_listener, run


    async def handle(client):
        async with client:
            name = await client.receive(1024)
            await client.send(b'Hello, %s\n' % name)


    async def main():
        listener = await create_unix_listener('/tmp/mysock')
        await listener.serve(handle)

    run(main)

Working with UDP sockets
------------------------

UDP (User Datagram Protocol) is a way of sending packets over the network without features like
connections, retries or error correction.

For example, if you wanted to create a UDP "hello" service that just reads a packet and then
sends a packet to the sender with the contents prepended with "Hello, ", you would do this::

    import socket

    from anyio import create_udp_socket, run


    async def main():
        async with await create_udp_socket(family=socket.AF_INET, local_port=1234) as udp:
            async for packet, (host, port) in udp:
                await udp.sendto(b'Hello, ' + packet, host, port)

    run(main)

If your use case involves sending lots of packets to a single destination, you can still "connect"
your UDP socket to a specific host and port to avoid having to pass the address and port every time
you send data to the peer::

    from anyio import create_connected_udp_socket, run


    async def main():
        async with await create_connected_udp_socket(
                remote_host='hostname', remote_port=1234) as udp:
            await udp.send(b'Hi there!\n')

    run(main)
