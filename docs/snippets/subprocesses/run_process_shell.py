from anyio import run, run_process


async def main() -> None:
    result = await run_process(["ps"])
    print(result.stdout.decode())


run(main)
