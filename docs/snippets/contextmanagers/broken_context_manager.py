from types import TracebackType
from typing import Self

from anyio import create_task_group


class MyBrokenContextManager:
    async def __aenter__(self) -> Self:
        self._task_group = await create_task_group().__aenter__()
        # BOOM: missing the "arg" argument here to my_background_func!
        self._task_group.start_soon(self.my_background_func)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return await self._task_group.__aexit__(exc_type, exc_value, traceback)

    async def my_background_func(self, arg: int) -> None: ...
