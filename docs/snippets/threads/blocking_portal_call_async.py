from anyio import run, to_thread
from anyio.from_thread import BlockingPortal


async def server_operation() -> str:
    return "result from the server's event loop"


async def user_code(portal: BlockingPortal) -> None:
    result = await portal.call_async(server_operation)
    print(result)


async def main() -> None:
    async with BlockingPortal() as portal:
        # Run the user-code event loop in a separate thread
        await to_thread.run_sync(run, user_code, portal)


run(main)
