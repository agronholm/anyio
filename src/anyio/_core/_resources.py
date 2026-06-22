from __future__ import annotations

from typing import TYPE_CHECKING

from ._tasks import CancelScope

if TYPE_CHECKING:
    from ..abc import AsyncResource


async def aclose_forcefully(resource: AsyncResource) -> None:
    """
    Close an asynchronous resource in a cancelled scope.

    Doing this closes the resource without waiting on anything.

    :param resource: the resource to close

    """
    with CancelScope() as scope:
        scope.cancel()
        await resource.aclose()
