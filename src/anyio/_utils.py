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


def convert_ipv6_sockaddr(sockaddr):
    """
    Convert a 4-tuple IPv6 socket address to a 2-tuple (address, port) format.

    If the scope ID is nonzero, it is added to the address, separated with ``%``.
    Otherwise the flow id and scope id are simply cut off from the tuple.
    Any other kinds of socket addresses are returned as-is.

    :param sockaddr: the result of :meth:`~socket.socket.getsockname`
    :return: the converted socket address

    """
    # This is more complicated than it should be because of MyPy
    if isinstance(sockaddr, tuple) and len(sockaddr) == 4:
        if sockaddr[3]:
            # Add scopeid to the address
            return sockaddr[0] + '%' + str(sockaddr[3]), sockaddr[1]
        else:
            return sockaddr[:2]
    else:
        return sockaddr


class NullAsyncContextManager:
    async def __aenter__(self):
        pass

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
