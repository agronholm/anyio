Streams
=======

.. py:currentmodule:: anyio

A "stream" in AnyIO is a simple interface for transporting information from one place to
another. It can mean either in-process communication or sending data over a network.
AnyIO divides streams into two categories: byte streams and object streams.

Byte streams ("Streams" in Trio lingo) are objects that receive and/or send chunks of
bytes. They are modelled after the limitations of the stream sockets, meaning the
boundaries are not respected. In practice this means that if, for example, you call
``.send(b'hello ')`` and then ``.send(b'world')``, the other end will receive the data
chunked in any arbitrary way, like (``b'hello'`` and ``b' world'``), ``b'hello world'``
or (``b'hel'``, ``b'lo wo'``, ``b'rld'``).

Object streams ("Channels" in Trio lingo), on the other hand, deal with Python objects.
The most commonly used implementation of these is the memory object stream. The exact
semantics of object streams vary a lot by implementation.

Many stream implementations wrap other streams. Of these, some can wrap any
bytes-oriented streams, meaning ``ObjectStream[bytes]`` and ``ByteStream``. This enables
many interesting use cases.

.. _memory object streams:

Memory object streams
---------------------

Memory object streams are intended for implementing a producer-consumer pattern with
multiple tasks. Using :func:`~create_memory_object_stream`, you get a pair of object
streams: one for sending, one for receiving. They essentially work like queues, but with
support for closing and asynchronous iteration.

By default, memory object streams are created with a buffer size of 0. This means that
:meth:`~.streams.memory.MemoryObjectSendStream.send` will block until there's another
task that calls :meth:`~.streams.memory.MemoryObjectReceiveStream.receive`. You can set
the buffer size to a value of your choosing when creating the stream. It is also
possible to have an unbounded buffer by passing :data:`math.inf` as the buffer size but
this is not recommended.

Memory object streams can be cloned by calling the ``clone()`` method. Each clone can be
closed separately, but each end of the stream is only considered closed once all of its
clones have been closed. For example, if you have two clones of the receive stream, the
send stream will start raising :exc:`~BrokenResourceError` only when both receive
streams have been closed.

Multiple tasks can send and receive on the same memory object stream (or its clones) but
each sent item is only ever delivered to a single recipient.

The receive ends of memory object streams can be iterated using the async iteration
protocol. The loop exits when all clones of the send stream have been closed.

Example::

    from anyio import create_task_group, create_memory_object_stream, run
    from anyio.streams.memory import MemoryObjectReceiveStream


    async def process_items(receive_stream: MemoryObjectReceiveStream[str]) -> None:
        async with receive_stream:
            async for item in receive_stream:
                print('received', item)


    async def main():
        # The [str] specifies the type of the objects being passed through the
        # memory object stream. This is a bit of trick, as create_memory_object_stream
        # is actually a class masquerading as a function.
        send_stream, receive_stream = create_memory_object_stream[str]()
        async with create_task_group() as tg:
            tg.start_soon(process_items, receive_stream)
            async with send_stream:
                for num in range(10):
                    await send_stream.send(f'number {num}')

    run(main)

In contrast to other AnyIO streams (but in line with Trio's Channels), memory object
streams can be closed synchronously, using either the ``close()`` method or by using the
stream as a context manager::

    from anyio.streams.memory import MemoryObjectSendStream


    def synchronous_callback(send_stream: MemoryObjectSendStream[str]) -> None:
        with send_stream:
            send_stream.send_nowait('hello')

Stapled streams
---------------

A stapled stream combines any mutually compatible receive and send stream together,
forming a single bidirectional stream.

It comes in two variants:

* :class:`~.streams.stapled.StapledByteStream` (combines a
  :class:`~.abc.ByteReceiveStream` with a :class:`~.abc.ByteSendStream`)
* :class:`~.streams.stapled.StapledObjectStream` (combines an
  :class:`~.abc.ObjectReceiveStream` with a compatible :class:`~.abc.ObjectSendStream`)

Buffered byte streams
---------------------

A buffered byte stream wraps an existing bytes-oriented receive stream and provides
certain amenities that require buffering, such as receiving an exact number of bytes, or
receiving until the given delimiter is found.

Example::

    from anyio import run, create_memory_object_stream
    from anyio.streams.buffered import BufferedByteReceiveStream


    async def main():
        send, receive = create_memory_object_stream[bytes](4)
        buffered = BufferedByteReceiveStream(receive)
        for part in b'hel', b'lo, ', b'wo', b'rld!':
            await send.send(part)

        result = await buffered.receive_exactly(8)
        print(repr(result))

        result = await buffered.receive_until(b'!', 10)
        print(repr(result))

    run(main)

The above script gives the following output::

    b'hello, w'
    b'orld'

Text streams
------------

Text streams wrap existing receive/send streams and encode/decode strings to bytes and
vice versa.

Example::

    from anyio import run, create_memory_object_stream
    from anyio.streams.text import TextReceiveStream, TextSendStream


    async def main():
        bytes_send, bytes_receive = create_memory_object_stream[bytes](1)
        text_send = TextSendStream(bytes_send)
        await text_send.send('åäö')
        result = await bytes_receive.receive()
        print(repr(result))

        text_receive = TextReceiveStream(bytes_receive)
        await bytes_send.send(result)
        result = await text_receive.receive()
        print(repr(result))

    run(main)

The above script gives the following output::

    b'\xc3\xa5\xc3\xa4\xc3\xb6'
    'åäö'

.. _FileStreams:

File streams
------------

File streams read from or write to files on the file system. They can be useful for
substituting a file for another source of data, or writing output to a file for logging
or debugging purposes.

Example::

    from anyio import run
    from anyio.streams.file import FileReadStream, FileWriteStream


    async def main():
        path = '/tmp/testfile'
        async with await FileWriteStream.from_path(path) as stream:
            await stream.send(b'Hello, World!')

        async with await FileReadStream.from_path(path) as stream:
            async for chunk in stream:
                print(chunk.decode(), end='')

        print()

    run(main)

.. versionadded:: 3.0


.. _TLS:

TLS streams
-----------

TLS (Transport Layer Security), the successor to SSL (Secure Sockets Layer), is the
supported way of providing authenticity and confidentiality for TCP streams in AnyIO.

TLS is typically established right after the connection has been made. The handshake
involves the following steps:

* Sending the certificate to the peer (usually just by the server)
* Checking the peer certificate(s) against trusted CA certificates
* Checking that the peer host name matches the certificate

Obtaining a server certificate
******************************

There are three principal ways you can get an X.509 certificate for your server:

#. Create a self signed certificate
#. Use certbot_ or a similar software to automatically obtain certificates from
   `Let's Encrypt`_
#. Buy one from a certificate vendor

The first option is probably the easiest, but this requires that any client
connecting to your server adds the self signed certificate to their list of trusted
certificates. This is of course impractical outside of local development and is strongly
discouraged in production use.

The second option is nowadays the recommended method, as long as you have an environment
where running certbot_ or similar software can automatically replace the certificate
with a newer one when necessary, and that you don't need any extra features like class 2
validation.

The third option may be your only valid choice when you have special requirements for
the certificate that only a certificate vendor can fulfill, or that automatically
renewing the certificates is not possible or practical in your environment.

.. _certbot: https://certbot.eff.org/
.. _Let's Encrypt: https://letsencrypt.org/

Using self signed certificates
******************************

To create a self signed certificate for ``localhost``, you can use the openssl_ command
line tool:

.. code-block:: bash

    openssl req -x509 -newkey rsa:2048 -subj '/CN=localhost' -keyout key.pem -out cert.pem -nodes -days 365

This creates a (2048 bit) private RSA key (``key.pem``) and a certificate (``cert.pem``)
matching the host name "localhost". The certificate will be valid for one year with
these settings.

To set up a server using this key-certificate pair::

    import ssl

    from anyio import create_tcp_listener, run
    from anyio.streams.tls import TLSListener


    async def handle(client):
        async with client:
            name = await client.receive()
            await client.send(b'Hello, %s\n' % name)


    async def main():
        # Create a context for the purpose of authenticating clients
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

        # Load the server certificate and private key
        context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')

        # Create the listener and start serving connections
        listener = TLSListener(await create_tcp_listener(local_port=1234), context)
        await listener.serve(handle)

    run(main)

Connecting to this server can then be done as follows::

    import ssl

    from anyio import connect_tcp, run


    async def main():
        # These two steps are only required for certificates that are not trusted by the
        # installed CA certificates on your machine, so you can skip this part if you
        # use Let's Encrypt or a commercial certificate vendor
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.load_verify_locations(cafile='cert.pem')

        async with await connect_tcp('localhost', 1234, ssl_context=context) as client:
            await client.send(b'Client\n')
            response = await client.receive()
            print(response)

    run(main)

.. _openssl: https://www.openssl.org/

Creating self-signed certificates on the fly
********************************************

When testing your TLS enabled service, it would be convenient to generate the
certificates on the fly. To this end, you can use the trustme_ library::

    import ssl

    import pytest
    import trustme


    @pytest.fixture(scope='session')
    def ca():
        return trustme.CA()


    @pytest.fixture(scope='session')
    def server_context(ca):
        server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ca.issue_cert('localhost').configure_cert(server_context)
        return server_context


    @pytest.fixture(scope='session')
    def client_context(ca):
        client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ca.configure_trust(client_context)
        return client_context

You can then pass the server and client contexts from the above fixtures to
:class:`~.streams.tls.TLSListener`, :meth:`~.streams.tls.TLSStream.wrap` or whatever you
use on either side.

.. _trustme: https://pypi.org/project/trustme/

Dealing with ragged EOFs
************************

According to the `TLS standard`_, encrypted connections should end with a closing
handshake. This practice prevents so-called `truncation attacks`_. However, broadly
available implementations for protocols such as HTTP, widely ignore this requirement
because the protocol level closing signal would make the shutdown handshake redundant.

AnyIO follows the standard by default (unlike the Python standard library's :mod:`ssl`
module). The practical implication of this is that if you're implementing a protocol
that is expected to skip the TLS closing handshake, you need to pass the
``standard_compatible=False`` option to :meth:`~.streams.tls.TLSStream.wrap` or
:class:`~.streams.tls.TLSListener`.

.. _TLS standard: https://tools.ietf.org/html/draft-ietf-tls-tls13-28
.. _truncation attacks: https://en.wikipedia.org/wiki/Transport_Layer_Security
   #Attacks_against_TLS/SSL
