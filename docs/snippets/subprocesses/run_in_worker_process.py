import time

from anyio import run, to_process


def cpu_intensive_function(arg1: str, arg2: str) -> str:
    time.sleep(1)
    return arg1 + arg2


async def main() -> None:
    result = await to_process.run_sync(cpu_intensive_function, "Hello, ", "world!")
    print(result)


# This check is important when the application uses to_process.run_sync()
if __name__ == "__main__":
    run(main)
