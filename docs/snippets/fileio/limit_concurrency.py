from anyio import CapacityLimiter, open_file, run


async def main() -> None:
    limiter = CapacityLimiter(5)
    async with await open_file("/foo/bar", limiter=limiter) as fp:
        contents = await fp.read()


run(main)
