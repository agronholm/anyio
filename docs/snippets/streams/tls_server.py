import ssl

from anyio import create_tcp_listener, run
from anyio.streams.tls import TLSListener, TLSStream


async def handle(client: TLSStream) -> None:
    async with client:
        name = await client.receive()
        await client.send(b"Hello, %s\n" % name)


async def main() -> None:
    # Create a context for the purpose of authenticating clients
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

    # Load the server certificate and private key
    context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

    # Create the listener and start serving connections
    listener = TLSListener(await create_tcp_listener(local_port=1234), context)
    await listener.serve(handle)


run(main)
