from ..abc import AsyncResource
from ._tasks import open_cancel_scope


async def aclose_forcefully(resource: AsyncResource) -> None:
    """
    Close an asynchronous resource in a cancelled scope.

    Doing this closes the resource without waiting on anything.

    :param resource: the resource to close

    """
    async with open_cancel_scope() as scope:
        await scope.cancel()
        await resource.aclose()
