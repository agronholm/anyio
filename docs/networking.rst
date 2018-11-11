Using sockets and streams
=========================

Networking capabilities are arguably the most important part of any asynchronous library.
AnyIO contains its own high level implementation of networking on top of low level primitives
offered by each of its supported backends.

Currently AnyIO offers the following networking functionality:

* TCP sockets (client + server, with TLS encryption support)
* UNIX domain sockets (client + server)
* UDP sockets

More exotic forms of networking such as raw sockets and SCTP are currently not supported.

Working with TCP sockets
------------------------

TCP (Transmission Control Protocol) is the most commonly used protocol on the Internet. It allows
one to connect to a port on a remote host and send and receive data in a reliable manner.

To connect to a listening TCP socket somewhere, you can use :func:`~anyio.connect_tcp`::

    from anyio import connect_tcp, run


    async def main():
        async with await connect_tcp('hostname', 1234) as client:
            await client.send_all(b'Client\n')
            response = await client.receive_until(b'\n', 1024)
            print(response)

    run(main)

To receive incoming TCP connections, you first create a TCP server with
:func:`anyio.create_tcp_server` and then asynchronously iterate over
:meth:`~anyio.abc.SocketStreamServer.accept_connections` and then hand off the yielded client
streams to their dedicated tasks::

    from anyio import create_task_group, create_tcp_server, run


    async def serve(client):
        async with client:
            name = await client.receive_until(b'\n', 1024)
            await client.send_all(b'Hello, %s\n' % name)


    async def main():
        async with create_task_group() as tg, await create_tcp_server(1234) as server:
            async for client in server.accept_connections():
                await tg.spawn(serve, client)

    run(main)

The ``async for`` loop will automatically exit when the server is closed.

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
            await client.send_all(b'Client\n')
            response = await client.receive_until(b'\n', 1024)
            print(response)

    run(main)

And the server::

    from anyio import create_task_group, create_unix_server, run


    async def serve(client):
        async with client:
            name = await client.receive_until(b'\n', 1024)
            await client.send_all(b'Hello, %s\n' % name)


    async def main():
        async with create_task_group() as tg, await create_unix_server('/tmp/mysock') as server:
            async for client in server.accept_connections():
                await tg.spawn(serve, client)

    run(main)

Working with UDP sockets
------------------------

UDP (User Datagram Protocol) is a way of sending packets over the network without features like
connections, retries or error correction.

For example, if you wanted to create a UDP "hello" service that just reads a packet and then
sends a packet to the sender with the contents prepended with "Hello, ", you would do this::

    from anyio import create_udp_socket, run


    async def main():
        async with await create_udp_socket(port=1234) as socket:
            async for packet, (host, port) in socket.receive_packets(1024):
                await socket.send(b'Hello, ' + packet, host, port)

    run(main)

If your use case involves sending lots of packets to a single destination, you can still "connect"
your UDP socket to a specific host and port to avoid having to pass the address and port every time
you send data to the peer::

    from anyio import create_udp_socket, run


    async def main():
        async with await create_udp_socket(target_host='hostname', target_port=1234) as socket:
            await socket.send(b'Hi there!\n')

    run(main)

Working with TLS
----------------

TLS (Transport Layer Security), the successor to SSL (Secure Sockets Layer), is the supported way
of providing authenticity and confidentiality for TCP streams in AnyIO.

TLS is typically established right after the connection has been made. The handshake involves the
following steps:

* Sending the certificate to the peer (usually just by the server)
* Checking the peer certificate(s) against trusted CA certificates
* Checking that the peer host name matches the certificate

Obtaining a server certificate
******************************

There are three principal ways you can get an X.509 certificate for your server:

#. Create a self signed certificate
#. Use certbot_ or a similar software to automatically obtain certificates from `Let's Encrypt`_
#. Buy one from a certificate vendor

The first option is probably the easiest, but this requires that the any client connecting to your
server adds the self signed certificate to their list of trusted certificates. This is of course
impractical outside of local development and is strongly discouraged in production use.

The second option is nowadays the recommended method, as long as you have an environment where
running certbot_ or similar software can automatically replace the certificate with a newer one
when necessary, and that you don't need any extra features like class 2 validation.

The third option may be your only valid choice when you have special requirements for the
certificate that only a certificate vendor can fulfill, or that automatically renewing the
certificates is not possible or practical in your environment.

.. _certbot: https://certbot.eff.org/
.. _Let's Encrypt: https://letsencrypt.org/

Using self signed certificates
******************************

To create a self signed certificate for ``localhost``, you can use the openssl_ command line tool:

.. code-block:: bash

    openssl req -x509 -newkey rsa:2048 -subj '/CN=localhost' -keyout key.pem -out cert.pem -nodes -days 365

This creates a (2048 bit) private RSA key (``key.pem``) and a certificate (``cert.pem``) matching
the host name "localhost". The certificate will be valid for one year with these settings.

To set up a server using this key-certificate pair::

    import ssl

    from anyio import create_task_group, create_tcp_server, run


    async def serve(client):
        async with client:
            name = await client.receive_until(b'\n', 1024)
            await client.send_all(b'Hello, %s\n' % name)


    async def main():
        # Create a context for the purpose of authenticating clients
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

        # Load the server certificate and private key
        context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')

        async with create_task_group() as tg:
            async with await create_tcp_server(1234, ssl_context=context) as server:
                async for client in server.accept_connections():
                    await tg.spawn(serve, client)

    run(main)

Connecting to this server can then be done as follows::

    import ssl

    from anyio import connect_tcp, run


    async def main():
        # These two steps are only required for certificates that are not trusted by the
        # installed CA certificates on your machine, so you can skip this part if you use
        # Let's Encrypt or a commercial certificate vendor
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.load_verify_locations(cafile='cert.pem')

        async with await connect_tcp('localhost', 1234, ssl_context=context, autostart_tls=True) as client:
            await client.send_all(b'Client\n')
            response = await client.receive_until(b'\n', 1024)
            print(response)

    run(main)


.. _openssl: https://www.openssl.org/

Manually establishing TLS
*************************

Some protocols, like FTP_ or IMAP_, support a technique called "opportunistic TLS". This means that
if the server advertises the capability of establishing a secure connection, the client can
initiate a TLS handshake after notifying the server using a protocol specific manner.

To do this, you want to prevent the automatic TLS handshake on the server by passing the
``autostart_tls=False`` option::

    import ssl

    from anyio import create_task_group, create_tcp_server, finalize, run


    async def serve(client):
        async with client, finalize(client.receive_delimited_chunks(b'\n', 100)) as lines:
            async for line in lines:
                print('Received "{}"'.format(line.decode('utf-8')))
                if line == b'STARTTLS':
                    await client.start_tls()
                elif line == b'QUIT':
                    return


    async def main():
        # Create a context for the purpose of authenticating clients
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

        # Load the server certificate and private key
        context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')

        async with create_task_group() as tg:
            async with await create_tcp_server(1234, ssl_context=context, autostart_tls=False) as server:
                async for client in server.accept_connections():
                    await tg.spawn(serve, client)

    run(main)

On the client, you will need to omit the ``autostart_tls`` option::

    import ssl

    from anyio import connect_tcp, run


    async def main():
        # Skip these unless connecting to a server with a self signed certificate
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.load_verify_locations(cafile='cert.pem')

        async with await connect_tcp('localhost', 1234, ssl_context=context) as client:
            await client.send_all(b'DUMMY\n')
            await client.send_all(b'STARTTLS\n')
            await client.start_tls()

            # From this point on, all communication is encrypted
            await client.send_all(b'ENCRYPTED\n')
            await client.send_all(b'QUIT\n')

    run(main)

.. _FTP: https://en.wikipedia.org/wiki/File_Transfer_Protocol
.. _IMAP: https://en.wikipedia.org/wiki/Internet_Message_Access_Protocol

Dealing with ragged EOFs
************************

According to the `TLS standard`_, encrypted connections should end with a shutdown handshake. This
practice prevents so-called `truncation attacks`_. However, broadly available implementations for
protocols such as HTTP, widely ignore this requirement because the protocol level closing signal
would make the shutdown handshake redundant.

AnyIO follows the standard by default (unlike the Python standard library's :mod:`ssl` module).
The practical implication of this is that if you're implementing a protocol that is expected to
skip the TLS shutdown handshake, you need to pass the ``tls_standard_compatible=False`` option to
:func:`connect_tcp` or :func:`create_tcp_server` (depending on whether you're implementing a client
or a server, obviously).

.. _TLS standard: https://tools.ietf.org/html/draft-ietf-tls-tls13-28
.. _truncation attacks: https://en.wikipedia.org/wiki/Transport_Layer_Security#Attacks_against_TLS/SSL
