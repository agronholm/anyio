from types import TracebackType

from anyio.from_thread import start_blocking_portal


class AsyncContextManager:
    async def __aenter__(self) -> None:
        print("entering")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        print("exiting with", exc_type)


async_cm = AsyncContextManager()
with start_blocking_portal() as portal, portal.wrap_async_context_manager(async_cm):
    print("inside the context manager block")
