Using sockets and streams
=========================

.. py:currentmodule:: anyio

Networking capabilities are arguably the most important part of any asynchronous
library. AnyIO contains its own high level implementation of networking on top of low
level primitives offered by each of its supported backends.

Currently AnyIO offers the following networking functionality:

* TCP sockets (client + server)
* UNIX domain sockets (client + server)
* UDP sockets
* UNIX datagram sockets

More exotic forms of networking such as raw sockets and SCTP are currently not
supported.

.. warning:: Unlike the standard BSD sockets interface and most other networking
    libraries, AnyIO (from 2.0 onwards) signals the end of any stream by raising the
    :exc:`~EndOfStream` exception instead of returning an empty bytes object.

Working with TCP sockets
------------------------

TCP (Transmission Control Protocol) is the most commonly used protocol on the Internet.
It allows one to connect to a port on a remote host and send and receive data in a
reliable manner.

To connect to a listening TCP socket somewhere, you can use :func:`~connect_tcp`::

    from anyio import connect_tcp, run


    async def main():
        async with await connect_tcp('hostname', 1234) as client:
            await client.send(b'Client\n')
            response = await client.receive()
            print(response)

    run(main)

As a convenience, you can also use :func:`~connect_tcp` to establish a TLS session with
the peer after connection, by passing ``tls=True`` or by passing a nonempty value for
either ``ssl_context`` or ``tls_hostname``.

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

UNIX domain sockets are a form of interprocess communication on UNIX-like operating
systems. They cannot be used to connect to remote hosts and do not work on Windows.

The API for UNIX domain sockets is much like the one for TCP sockets, except that
instead of host/port combinations, you use file system paths.

This is what the client from the TCP example looks like when converted to use UNIX
sockets::

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

.. note:: The UNIX socket listener does not remove the socket it creates, so you may
   need to delete them manually.

Sending and receiving file descriptors
++++++++++++++++++++++++++++++++++++++

UNIX sockets can be used to pass open file descriptors (sockets and files) to another
process. The receiving end can then use either :func:`os.fdopen` or
:class:`socket.socket` to get a usable file or socket object, respectively.

The following is an example where a client connects to a UNIX socket server and receives
the descriptor of a file opened on the server, reads the contents of the file and then
prints them on standard output.

Client::

    import os

    from anyio import connect_unix, run


    async def main():
        async with await connect_unix('/tmp/mysock') as client:
            _, fds = await client.receive_fds(0, 1)
            with os.fdopen(fds[0]) as file:
                print(file.read())

    run(main)

Server::

    from pathlib import Path

    from anyio import create_unix_listener, run


    async def handle(client):
        async with client:
            with path.open('r') as file:
                await client.send_fds(b'this message is ignored', [file])


    async def main():
        listener = await create_unix_listener('/tmp/mysock')
        await listener.serve(handle)

    path = Path('/tmp/examplefile')
    path.write_text('Test file')
    run(main)

Working with UDP sockets
------------------------

UDP (User Datagram Protocol) is a way of sending packets over the network without
features like connections, retries or error correction.

For example, if you wanted to create a UDP "hello" service that just reads a packet and
then sends a packet to the sender with the contents prepended with "Hello, ", you would
do this::

    import socket

    from anyio import create_udp_socket, run


    async def main():
        async with await create_udp_socket(
            family=socket.AF_INET, local_port=1234
        ) as udp:
            async for packet, (host, port) in udp:
                await udp.sendto(b'Hello, ' + packet, host, port)

    run(main)

.. note:: If you are testing on your local machine or don't know which family socket to
   use, it is a good idea to replace ``family=socket.AF_INET`` by
   ``local_host='localhost'`` in the previous example.

If your use case involves sending lots of packets to a single destination, you can still
"connect" your UDP socket to a specific host and port to avoid having to pass the
address and port every time you send data to the peer::

    from anyio import create_connected_udp_socket, run


    async def main():
        async with await create_connected_udp_socket(
                remote_host='hostname', remote_port=1234) as udp:
            await udp.send(b'Hi there!\n')

    run(main)

Working with UNIX datagram sockets
----------------------------------

UNIX datagram sockets are a subset of UNIX domain sockets, with the difference being
that while UNIX sockets implement reliable communication of a continuous byte stream
(similarly to TCP), UNIX datagram sockets implement communication of data packets
(similarly to UDP).

The API for UNIX datagram sockets is modeled after the one for UDP sockets, except that
instead of host/port combinations, you use file system paths - here is the UDP "hello"
service example written with UNIX datagram sockets::

    from anyio import create_unix_datagram_socket, run


    async def main():
        async with await create_unix_datagram_socket(
            local_path='/tmp/mysock'
        ) as unix_dg:
            async for packet, path in unix_dg:
                await unix_dg.sendto(b'Hello, ' + packet, path)

    run(main)


.. note:: If ``local_path`` is not set, the UNIX datagram socket will be bound on an
   unnamed address, and will generally not be able to receive datagrams from other UNIX
   datagram sockets.

Similarly to UDP sockets, if your case involves sending lots of packets to a single
destination, you can "connect" your UNIX datagram socket to a specific path to avoid
having to pass the path every time you send data to the peer::

    from anyio import create_connected_unix_datagram_socket, run


    async def main():
        async with await create_connected_unix_datagram_socket(
            remote_path='/dev/log'
        ) as unix_dg:
            await unix_dg.send(b'Hi there!\n')

    run(main)

Wrapping existing sockets as streams or listeners
-------------------------------------------------

In some cases, you might want to create a socket in third party code and wrap that as an
AnyIO stream or socket listener. For that, various class methods exist:

* :meth:`.abc.SocketListener.from_socket`
* :meth:`.abc.SocketStream.from_socket`
* :meth:`.abc.UNIXSocketStream.from_socket`
* :meth:`.abc.UDPSocket.from_socket`
* :meth:`.abc.ConnectedUDPSocket.from_socket`
* :meth:`.abc.UNIXDatagramSocket.from_socket`
* :meth:`.abc.ConnectedUNIXDatagramSocket.from_socket`

.. _connectables:

Abstracting remote connections using Connectables
-------------------------------------------------

AnyIO offers a hierarchy of classes implementing either the
:class:`.abc.ObjectStreamConnectable` or :class:`.abc.ByteStreamConnectable` interfaces
which lets developers abstract out the connection mechanism for network clients.
For example, you could create a network client class like this::

    from os import PathLike
    from ssl import SSLContext

    from anyio.abc import ByteStreamConnectable, as_connectable


    class MyNetworkClient:
        def __init__(
            self,
            connectable: ByteStreamConnectable | tuple[str, int] | str | PathLike[str],
            tls: bool | SSLContext = False
        ):
            self.connectable = as_connectable(connectable, tls)

        async def __aenter__(self):
            # Connect to the remote and enter the stream's context manager
            self._stream = await self.connectable.connect()
            await self._stream.__aenter__()
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            # Exit the stream's context manager, thus disconnecting it
            await self._stream.__aexit__(exc_type, exc_val, exc_tb)

Here's a dissection of the type annotation for ``connectable``:

* :class:`.abc.ByteStreamConnectable`: allows for any arbitrary bytestream connectable
* ``tuple[str, int]``: TCP host/port
* ``str | bytes | PathLike[str]``: file system path to a UNIX socket

The :func:`as_connectable` function is a convenience that lets users instantiate your
client without the hassle of manually instantiating a connectable like
:class:`TCPConnectable` or :class:`UNIXConnectable`.

So why bother jumping through these extra hoops? Because it gives users the flexibility
of using more exotic transports, such as:

* Mock streams (for testing)
* Interceptor streams (for testing network delays, stalled connections, etc.)
* SOCKS proxies
* HTTP tunneling via ``CONNECT``

In particular, tunneling using AnyIO streams rather than external connectors has the
advantage of allowing passthrough of information such as the peer address via
:meth:`~TypedAttributeProvider.extra`.

In addition to that, it greatly simplifies adding support for TLS and transports other
than TCP.
