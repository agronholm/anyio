from anyio import move_on_after
from anyio.abc import AsyncResource


async def do_something(resource: AsyncResource) -> None:
    try:
        ...
    except BaseException:
        # Here we wait 10 seconds for resource.aclose() to complete,
        # but if the operation doesn't complete within that period, we move on
        # and re-raise the caught exception anyway
        with move_on_after(10, shield=True):
            await resource.aclose()

        raise
