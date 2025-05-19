from __future__ import annotations

from abc import ABCMeta, abstractmethod
from types import TracebackType
from typing import Generic, TypeVar, cast, final
from warnings import warn

T = TypeVar("T")
T_resource = TypeVar("T_resource", bound="AsyncResource")


class AsyncResource(metaclass=ABCMeta):
    """
    Abstract base class for all closeable asynchronous resources.

    Works as an asynchronous context manager which returns the instance itself on enter,
    and calls :meth:`aclose` on exit.
    """

    __slots__ = ()

    async def __aenter__(self: T) -> T:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    @abstractmethod
    async def aclose(self) -> None:
        """Close the resource."""


class ResourcePool(Generic[T_resource], AsyncResource):
    """Abstract class for providing pools of closeable resources."""

    def __init__(self, max_size: int):
        from anyio import Semaphore

        if not isinstance(max_size, int):
            raise TypeError("max_size must be an integer")
        elif max_size < 1:
            raise ValueError("max_size must be >= 1")

        self._semaphore = Semaphore(max_size)
        self._available_resources: list[T_resource] = []
        self._checked_out_resources: list[T_resource] = []
        self._closed: bool = False

    @property
    def max_size(self) -> int:
        return cast(int, self._semaphore.max_value)

    @property
    def size(self) -> int:
        return len(self._available_resources) + len(self._checked_out_resources)

    @property
    def checked_out(self) -> int:
        return len(self._checked_out_resources)

    @property
    def available(self) -> int:
        return self.max_size - self.checked_out

    @property
    def closed(self) -> bool:
        """``True`` if this pool has been closed, ``False`` otherwise."""
        return self._closed

    @final
    async def acquire(self) -> T_resource:
        """
        Acquire a resource from the pool.

        This method blocks if the maximum number of resources have already been
        checked out.

        :return: a resource instance from the pool

        .. note:: Always call :meth:`release` to return a resource after you're done
            with it.

        """
        if self._closed:
            raise RuntimeError(f"this {self.__class__.__qualname__} is closed")

        async with self._semaphore:
            while self._available_resources:
                resource = self._available_resources.pop()
                try:
                    await self.validate_resource(resource)
                except BaseException as exc:
                    from anyio import aclose_forcefully

                    await aclose_forcefully(resource)
                    if not isinstance(exc, Exception):
                        raise
                else:
                    break
            else:
                resource = await self.create_resource()
                self._checked_out_resources.append(resource)

            return resource

    @final
    def release(self, resource: T_resource, /) -> None:
        self._checked_out_resources.remove(resource)
        self._available_resources.append(resource)

    @abstractmethod
    async def create_resource(self) -> T_resource:
        """
        Implement this method to return a new resource instance.

        .. warning:: Do not call this method directly.
        """

    async def validate_resource(self, resource: T_resource) -> bool:
        """
        Implement this method to validate a resource before it is returned from
        :meth:`acquire`.

        The default implementation always returns ``True``.

        :param resource: the resource to be validated
        :return: ``True`` if the resource is still valid, ``False`` otherwise

        .. warning:: Do not call this method directly.

        """
        return True

    @final
    async def aclose(self) -> None:
        from anyio import create_task_group

        self._closed = True
        async with create_task_group() as tg:
            resources = list(self._available_resources) + list(
                self._checked_out_resources
            )
            self._available_resources.clear()
            self._checked_out_resources.clear()
            for resource in resources:
                tg.start_soon(resource.aclose)

    def __del__(self) -> None:
        if self.size:
            warn(
                f"{self.__class__.__qualname__} was garbage collected with {self.size} "
                f"unclosed resources. Please either call aclose() or use 'async with' "
                f"to ensure resources are cleaned up properly.",
                ResourceWarning,
                stacklevel=1,
            )
