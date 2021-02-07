from .._core._eventloop import get_asynclib


async def checkpoint():
    """Checks for cancellation and allows the scheduler to switch to another task."""
    await get_asynclib().checkpoint()
