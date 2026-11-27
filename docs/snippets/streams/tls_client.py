import ssl

from anyio import connect_tcp, run


async def main() -> None:
    # These two steps are only required for certificates that are not trusted by the
    # installed CA certificates on your machine, so you can skip this part if you
    # use Let's Encrypt or a commercial certificate vendor
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    context.load_verify_locations(cafile="cert.pem")

    async with await connect_tcp("localhost", 1234, ssl_context=context) as client:
        await client.send(b"Client\n")
        response = await client.receive()
        print(response)


run(main)
