from ._core._eventloop import get_asynclib


async def checkpoint() -> None:
    """
    Check for cancellation and allow the scheduler to switch to another task.

    Equivalent to (but more efficient than)::

        await checkpoint_if_cancelled()
        await cancel_shielded_checkpoint()

    .. versionadded:: 3.0

    """
    await get_asynclib().checkpoint()


async def checkpoint_if_cancelled():
    """
    Enter a checkpoint if the enclosing cancel scope has been cancelled.

    This does not allow the scheduler to switch to a different task.

    .. versionadded:: 3.0

    """
    await get_asynclib().checkpoint_if_cancelled()


async def cancel_shielded_checkpoint() -> None:
    """
    Allow the scheduler to switch to another task but without checking for cancellation.

    Equivalent to (but potentially more efficient than)::

        with open_cancel_scope(shield=True):
            await checkpoint()

    .. versionadded:: 3.0

    """
    await get_asynclib().cancel_shielded_checkpoint()
