from collections import OrderedDict, deque
from dataclasses import dataclass, field
from types import TracebackType
from typing import Deque, Generic, List, NamedTuple, Optional, Type, TypeVar

from .. import (
    BrokenResourceError, ClosedResourceError, EndOfStream, WouldBlock, get_cancelled_exc_class)
from .._core._compat import DeprecatedAwaitable
from ..abc import Event, ObjectReceiveStream, ObjectSendStream
from ..lowlevel import checkpoint

T_Item = TypeVar('T_Item')


class MemoryObjectStreamStatistics(NamedTuple):
    current_buffer_used: int
    max_buffer_size: float
    open_send_streams: int
    open_receive_streams: int
    tasks_waiting_send: int
    tasks_waiting_receive: int


@dataclass(eq=False)
class MemoryObjectStreamState(Generic[T_Item]):
    max_buffer_size: float = field()
    buffer: Deque[T_Item] = field(init=False, default_factory=deque)
    open_send_channels: int = field(init=False, default=0)
    open_receive_channels: int = field(init=False, default=0)
    waiting_receivers: 'OrderedDict[Event, List[T_Item]]' = field(init=False,
                                                                  default_factory=OrderedDict)
    waiting_senders: 'OrderedDict[Event, T_Item]' = field(init=False, default_factory=OrderedDict)

    def statistics(self) -> MemoryObjectStreamStatistics:
        return MemoryObjectStreamStatistics(
            len(self.buffer), self.max_buffer_size, self.open_send_channels,
            self.open_receive_channels, len(self.waiting_senders), len(self.waiting_receivers))


@dataclass(eq=False)
class MemoryObjectReceiveStream(Generic[T_Item], ObjectReceiveStream[T_Item]):
    _state: MemoryObjectStreamState[T_Item]
    _closed: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self._state.open_receive_channels += 1

    def receive_nowait(self) -> T_Item:
        """
        Receive the next item if it can be done without waiting.

        :return: the received item
        :raises ~anyio.ClosedResourceError: if this send stream has been closed
        :raises ~anyio.EndOfStream: if the buffer is empty and this stream has been
            closed from the sending end
        :raises ~anyio.WouldBlock: if there are no items in the buffer and no tasks
            waiting to send

        """
        if self._closed:
            raise ClosedResourceError

        if self._state.waiting_senders:
            # Get the item from the next sender
            send_event, item = self._state.waiting_senders.popitem(last=False)
            self._state.buffer.append(item)
            send_event.set()

        if self._state.buffer:
            return self._state.buffer.popleft()
        elif not self._state.open_send_channels:
            raise EndOfStream

        raise WouldBlock

    async def receive(self) -> T_Item:
        await checkpoint()
        try:
            return self.receive_nowait()
        except WouldBlock:
            # Add ourselves in the queue
            receive_event = Event()
            container: List[T_Item] = []
            self._state.waiting_receivers[receive_event] = container

            try:
                await receive_event.wait()
            except get_cancelled_exc_class():
                # Ignore the immediate cancellation if we already received an item, so as not to
                # lose it
                if not container:
                    raise
            finally:
                self._state.waiting_receivers.pop(receive_event, None)

            if container:
                return container[0]
            else:
                raise EndOfStream

    def clone(self) -> 'MemoryObjectReceiveStream':
        """
        Create a clone of this receive stream.

        Each clone can be closed separately. Only when all clones have been closed will the
        receiving end of the memory stream be considered closed by the sending ends.

        :return: the cloned stream

        """
        if self._closed:
            raise ClosedResourceError

        return MemoryObjectReceiveStream(_state=self._state)

    def close(self) -> None:
        """
        Close the stream.

        This works the exact same way as :meth:`aclose`, but is provided as a special case for the
        benefit of synchronous callbacks.

        """
        if not self._closed:
            self._closed = True
            self._state.open_receive_channels -= 1
            if self._state.open_receive_channels == 0:
                send_events = list(self._state.waiting_senders.keys())
                for event in send_events:
                    event.set()

    async def aclose(self) -> None:
        self.close()

    def statistics(self) -> MemoryObjectStreamStatistics:
        """
        Return statistics about the current state of this stream.

        .. versionadded:: 3.0
        """
        return self._state.statistics()

    def __enter__(self) -> 'MemoryObjectReceiveStream[T_Item]':
        return self

    def __exit__(self, exc_type: Optional[Type[BaseException]],
                 exc_val: Optional[BaseException],
                 exc_tb: Optional[TracebackType]) -> None:
        self.close()


@dataclass(eq=False)
class MemoryObjectSendStream(Generic[T_Item], ObjectSendStream[T_Item]):
    _state: MemoryObjectStreamState[T_Item]
    _closed: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self._state.open_send_channels += 1

    def send_nowait(self, item: T_Item) -> DeprecatedAwaitable:
        """
        Send an item immediately if it can be done without waiting.

        :param item: the item to send
        :raises ~anyio.ClosedResourceError: if this send stream has been closed
        :raises ~anyio.BrokenResourceError: if the stream has been closed from the
            receiving end
        :raises ~anyio.WouldBlock: if the buffer is full and there are no tasks waiting
            to receive

        """
        if self._closed:
            raise ClosedResourceError
        if not self._state.open_receive_channels:
            raise BrokenResourceError

        if self._state.waiting_receivers:
            receive_event, container = self._state.waiting_receivers.popitem(last=False)
            container.append(item)
            receive_event.set()
        elif len(self._state.buffer) < self._state.max_buffer_size:
            self._state.buffer.append(item)
        else:
            raise WouldBlock

        return DeprecatedAwaitable(self.send_nowait)

    async def send(self, item: T_Item) -> None:
        await checkpoint()
        try:
            self.send_nowait(item)
        except WouldBlock:
            # Wait until there's someone on the receiving end
            send_event = Event()
            self._state.waiting_senders[send_event] = item
            try:
                await send_event.wait()
            except BaseException:
                self._state.waiting_senders.pop(send_event, None)  # type: ignore[arg-type]
                raise

            if self._state.waiting_senders.pop(send_event, None):  # type: ignore[arg-type]
                raise BrokenResourceError

    def clone(self) -> 'MemoryObjectSendStream':
        """
        Create a clone of this send stream.

        Each clone can be closed separately. Only when all clones have been closed will the
        sending end of the memory stream be considered closed by the receiving ends.

        :return: the cloned stream

        """
        if self._closed:
            raise ClosedResourceError

        return MemoryObjectSendStream(_state=self._state)

    def close(self) -> None:
        """
        Close the stream.

        This works the exact same way as :meth:`aclose`, but is provided as a special case for the
        benefit of synchronous callbacks.

        """
        if not self._closed:
            self._closed = True
            self._state.open_send_channels -= 1
            if self._state.open_send_channels == 0:
                receive_events = list(self._state.waiting_receivers.keys())
                self._state.waiting_receivers.clear()
                for event in receive_events:
                    event.set()

    async def aclose(self) -> None:
        self.close()

    def statistics(self) -> MemoryObjectStreamStatistics:
        """
        Return statistics about the current state of this stream.

        .. versionadded:: 3.0
        """
        return self._state.statistics()

    def __enter__(self) -> 'MemoryObjectSendStream[T_Item]':
        return self

    def __exit__(self, exc_type: Optional[Type[BaseException]],
                 exc_val: Optional[BaseException],
                 exc_tb: Optional[TracebackType]) -> None:
        self.close()
