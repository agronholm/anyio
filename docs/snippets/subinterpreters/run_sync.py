from yourothermodule import cpu_intensive_function

from anyio import run, to_interpreter


async def main() -> None:
    result = await to_interpreter.run_sync(cpu_intensive_function, "Hello, ", "world!")
    print(result)


run(main)
