from anyio import ResourceGuard


class Resource:
    def __init__(self) -> None:
        self._guard = ResourceGuard()

    async def do_something(self) -> None:
        with self._guard:
            ...
