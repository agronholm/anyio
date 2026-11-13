from typing import Any

from anyio.from_thread import BlockingPortalProvider


class MyAPI:
    def __init__(self, async_obj: Any) -> None:
        self._async_obj = async_obj
        self._portal_provider = BlockingPortalProvider()

    def do_stuff(self) -> None:
        with self._portal_provider as portal:
            portal.call(self._async_obj.do_async_stuff)
