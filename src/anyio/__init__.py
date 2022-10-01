from __future__ import annotations

__all__ = (
    "run",
    "sleep",
    "sleep_forever",
    "sleep_until",
    "current_time",
    "get_all_backends",
    "get_cancelled_exc_class",
    "BrokenResourceError",
    "BrokenWorkerProcess",
    "BusyResourceError",
    "ClosedResourceError",
    "DelimiterNotFound",
    "EndOfStream",
    "IncompleteRead",
    "TypedAttributeLookupError",
    "WouldBlock",
    "AsyncFile",
    "Path",
    "open_file",
    "wrap_file",
    "aclose_forcefully",
    "open_signal_receiver",
    "connect_tcp",
    "connect_unix",
    "create_tcp_listener",
    "create_unix_listener",
    "create_udp_socket",
    "create_connected_udp_socket",
    "create_unix_datagram_socket",
    "create_connected_unix_datagram_socket",
    "getaddrinfo",
    "getnameinfo",
    "wait_socket_readable",
    "wait_socket_writable",
    "create_memory_object_stream",
    "run_process",
    "open_process",
    "CapacityLimiter",
    "CapacityLimiterStatistics",
    "Condition",
    "ConditionStatistics",
    "Event",
    "EventStatistics",
    "Lock",
    "LockStatistics",
    "Semaphore",
    "SemaphoreStatistics",
    "fail_after",
    "move_on_after",
    "current_effective_deadline",
    "TASK_STATUS_IGNORED",
    "CancelScope",
    "create_task_group",
    "TaskInfo",
    "get_current_task",
    "get_running_tasks",
    "wait_all_tasks_blocked",
    "start_blocking_portal",
    "typed_attribute",
    "TypedAttributeSet",
    "TypedAttributeProvider",
)

from typing import Any

from ._core._eventloop import (
    current_time,
    get_all_backends,
    get_cancelled_exc_class,
    run,
    sleep,
    sleep_forever,
    sleep_until,
)
from ._core._exceptions import (
    BrokenResourceError,
    BrokenWorkerProcess,
    BusyResourceError,
    ClosedResourceError,
    DelimiterNotFound,
    EndOfStream,
    IncompleteRead,
    TypedAttributeLookupError,
    WouldBlock,
)
from ._core._fileio import AsyncFile, Path, open_file, wrap_file
from ._core._resources import aclose_forcefully
from ._core._signals import open_signal_receiver
from ._core._sockets import (
    connect_tcp,
    connect_unix,
    create_connected_udp_socket,
    create_connected_unix_datagram_socket,
    create_tcp_listener,
    create_udp_socket,
    create_unix_datagram_socket,
    create_unix_listener,
    getaddrinfo,
    getnameinfo,
    wait_socket_readable,
    wait_socket_writable,
)
from ._core._streams import create_memory_object_stream
from ._core._subprocesses import open_process, run_process
from ._core._synchronization import (
    CapacityLimiter,
    CapacityLimiterStatistics,
    Condition,
    ConditionStatistics,
    Event,
    EventStatistics,
    Lock,
    LockStatistics,
    Semaphore,
    SemaphoreStatistics,
)
from ._core._tasks import (
    TASK_STATUS_IGNORED,
    CancelScope,
    create_task_group,
    current_effective_deadline,
    fail_after,
    move_on_after,
)
from ._core._testing import (
    TaskInfo,
    get_current_task,
    get_running_tasks,
    wait_all_tasks_blocked,
)
from ._core._typedattr import TypedAttributeProvider, TypedAttributeSet, typed_attribute

# Re-export imports so they look like they live directly in this package
key: str
value: Any
for key, value in list(locals().items()):
    if getattr(value, "__module__", "").startswith("anyio."):
        value.__module__ = __name__
