from .exceptions import BusyResourceError


class ResourceGuard:
    __slots__ = 'action', '_guarded'

    def __init__(self, action: str):
        self.action = action
        self._guarded = False

    def __enter__(self):
        if self._guarded:
            raise BusyResourceError(self.action)

        self._guarded = True

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._guarded = False
