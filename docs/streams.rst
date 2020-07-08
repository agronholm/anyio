Streams
=======

A "stream" in AnyIO is a simple interface for transporting information from one place to another.
It can mean either in-process communication or sending data over a network.
AnyIO divides streams into two categories: byte streams and object streams.

Byte streams ("Streams" in Trio lingo) are objects that receive and/or send chunks of bytes.
They are modelled after the limitations of the stream sockets, meaning the boundaries are not
respected. In practice this means that if, for example, you call ``.send(b'hello ')`` and then
``.send(b'world')``, the other end will receive the data chunked in any arbitrary way, like
(``b'hello'`` and ``b'world'``), ``b'hello world'`` or (``b'hel'``, ``b'lo wo'``, ``b'rld'``).

Object streams ("Channels" in Trio lingo), on the other hand, deal with Python objects. The most
commonly used implementation of these is the memory object stream. The exact semantics of object
streams vary a lot by implementation.

Many stream implementations wrap other streams. Of these, some can wrap any bytes-oriented streams,
meaning ``ObjectStream[bytes]`` and ``ByteStream``. This enables many interesting use cases.

Stapled streams
---------------

A stapled stream combines any mutually compatible receive and send stream together, forming a
single bidirectional stream.

It comes in two variants:

* :class:`~anyio.streams.stapled.StapledByteStream` (combines a
    :class:`~anyio.abc.streams.ByteReceiveStream` with a
    :class:`~anyio.abc.streams.ByteSendStream`)
* :class:`~anyio.streams.stapled.StapledObjectStream` (combines an
    :class:`~anyio.abc.streams.ObjectReceiveStream` with a compatible
    :class:`~anyio.abc.streams.ObjectSendStream`)

Buffered byte streams
---------------------

A buffered byte stream wraps an existing bytes-oriented receive stream and provides certain
amenities that require buffering, such as receiving an exact number of bytes, or receiving until
the given delimiter is found.

Text streams
------------

Text streams wrap existing receive/send streams and encode/decode strings to bytes and vice versa.


Memory object streams
---------------------

Memory object streams are intended for implementing a producer-consumer pattern with multiple
tasks. Using :func:`~anyio.create_memory_object_stream`, you get a pair of object streams: one for
sending, one for receiving.

By default, memory object streams are created with a buffer size of 0. This means that
:meth:`~anyio.streams.memory.MemoryObjectSendStream.send` will block until there's another task
that calls :meth:`~anyio.streams.memory.MemoryObjectReceiveStream.receive`. You can set the buffer
size to a value of your choosing when creating the stream. It is also possible to have an unbounded
buffer by passing :data:``math.inf`` as the buffer size but this is not recommended.

Memory object streams can be cloned by calling the ``clone()`` method. Each clone can be closed
separately, but each end of the stream is only considered closed once all of its clones have been
closed. For example, if you have two clones of the receive stream, the send stream will start
raising :exc:`~anyio.exceptions.BrokenResourceError` only when both receive streams have been
closed.

Multiple tasks can send and receive on the same memory object stream (or its clones) but each sent
item is only ever delivered to a single recipient.

The receive ends of memory object streams can be iterated using the async iteration protocol.
The loop exits when all clones of the send stream have been closed.

Example::

    from anyio import create_task_group, create_memory_object_stream, run


    async def process_items(receive_stream):
        async with receive_stream:
            async for item in receive_stream:
                print('received', item)


    async def main():
        send_stream, receive_stream = create_memory_object_stream()
        async with create_task_group() as tg:
            await tg.spawn(process_items, receive_stream)
            async with send_stream:
                for num in range(10):
                    await send_stream.send(f'number {num}')

    run(main)

.. _TLS:

TLS streams
-----------

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

Dealing with ragged EOFs
************************

According to the `TLS standard`_, encrypted connections should end with a closing handshake. This
practice prevents so-called `truncation attacks`_. However, broadly available implementations for
protocols such as HTTP, widely ignore this requirement because the protocol level closing signal
would make the shutdown handshake redundant.

AnyIO follows the standard by default (unlike the Python standard library's :mod:`ssl` module).
The practical implication of this is that if you're implementing a protocol that is expected to
skip the TLS closing handshake, you need to pass the ``standard_compatible=False`` option to
:meth:`~anyio.streams.tls.TLSStream.wrap` or :class:`~anyio.streams.tls.TLSListener`.

.. _TLS standard: https://tools.ietf.org/html/draft-ietf-tls-tls13-28
.. _truncation attacks: https://en.wikipedia.org/wiki/Transport_Layer_Security#Attacks_against_TLS/SSL
