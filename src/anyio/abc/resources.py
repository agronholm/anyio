from abc import ABCMeta, abstractmethod
from types import TracebackType
from typing import Optional, Type


class AsyncResource(metaclass=ABCMeta):
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> None:
        await self.aclose()

    @abstractmethod
    async def aclose(self) -> None:
        """Close the resource."""
