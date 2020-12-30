from warnings import warn

from ._eventloop import sleep


class DeprecationWarner:
    def __init__(self, method: str):
        self._method = method

    def __await__(self):
        warn(f'Awaiting on {self._method} has been deprecated', category=DeprecationWarning)
        return sleep(0).__await__()
