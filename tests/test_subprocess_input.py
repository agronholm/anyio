from __future__ import annotations

import sys
from subprocess import run
from textwrap import dedent

import pytest


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
@pytest.mark.parametrize("input", [None, b"", b"explicit input"])
def test_run_process_input(backend: str, input: bytes | None) -> None:
    pytest.importorskip(backend)
    script = dedent(
        f"""\
        import sys
        import anyio

        async def main():
            result = await anyio.run_process(
                [sys.executable, "-c",
                 "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
                input={input!r},
            )
            sys.stdout.buffer.write(result.stdout)

        anyio.run(main, backend={backend!r})
        """
    )
    # Give the parent real stdin data: empty input must not inherit that stream.
    result = run(
        [sys.executable, "-c", script],
        input=b"inherited input",
        capture_output=True,
        check=True,
        timeout=10,
    )

    assert result.stdout == (b"inherited input" if input is None else input)
