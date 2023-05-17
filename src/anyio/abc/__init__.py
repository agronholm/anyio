from __future__ import annotations

from typing import Any

from ._eventloop import AsyncBackend
from ._resources import AsyncResource
from ._sockets import ConnectedUDPSocket
from ._sockets import ConnectedUNIXDatagramSocket
from ._sockets import IPAddressType
from ._sockets import IPSockAddrType
from ._sockets import SocketAttribute
from ._sockets import SocketListener
from ._sockets import SocketStream
from ._sockets import UDPPacketType
from ._sockets import UDPSocket
from ._sockets import UNIXDatagramPacketType
from ._sockets import UNIXDatagramSocket
from ._sockets import UNIXSocketStream
from ._streams import AnyByteReceiveStream
from ._streams import AnyByteSendStream
from ._streams import AnyByteStream
from ._streams import AnyUnreliableByteReceiveStream
from ._streams import AnyUnreliableByteSendStream
from ._streams import AnyUnreliableByteStream
from ._streams import ByteReceiveStream
from ._streams import ByteSendStream
from ._streams import ByteStream
from ._streams import Listener
from ._streams import ObjectReceiveStream
from ._streams import ObjectSendStream
from ._streams import ObjectStream
from ._streams import UnreliableObjectReceiveStream
from ._streams import UnreliableObjectSendStream
from ._streams import UnreliableObjectStream
from ._subprocesses import Process
from ._tasks import TaskGroup
from ._tasks import TaskStatus
from ._testing import TestRunner

# Re-exported here, for backwards compatibility
# isort: off
from .._core._synchronization import (
    CapacityLimiter,
    Condition,
    Event,
    Lock,
    Semaphore,
)
from .._core._tasks import CancelScope
from ..from_thread import BlockingPortal

# Re-export imports so they look like they live directly in this package
for value in list(locals().copy().values()):
    if getattr(value, "__module__", "").startswith("anyio.abc."):
        value.__module__ = __name__
