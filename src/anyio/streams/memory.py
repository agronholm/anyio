from collections import deque, OrderedDict
from dataclasses import dataclass, field
from typing import TypeVar, Generic, List, Deque, Tuple

from .. import get_cancelled_exc_class
from .._core._lowlevel import checkpoint
from .._core._synchronization import create_event
from ..abc.synchronization import Event
from ..abc.streams import ObjectSendStream, ObjectReceiveStream
from ..exceptions import ClosedResourceError, BrokenResourceError, WouldBlock, EndOfStream

T_Item = TypeVar('T_Item')


@dataclass
class MemoryObjectStreamState(Generic[T_Item]):
    max_buffer_size: float = field()
    buffer: Deque[T_Item] = field(init=False, default_factory=deque)
    open_send_channels: int = field(init=False, default=0)
    open_receive_channels: int = field(init=False, default=0)
    waiting_receivers: Deque[Tuple[Event, List[T_Item]]] = field(init=False, default_factory=deque)
    waiting_senders: 'OrderedDict[Event, T_Item]' = field(init=False, default_factory=OrderedDict)


@dataclass
class MemoryObjectReceiveStream(Generic[T_Item], ObjectReceiveStream[T_Item]):
    _state: MemoryObjectStreamState[T_Item]
    _closed: bool = field(init=False, default=False)

    def __post_init__(self):
        self._state.open_receive_channels += 1

    async def receive_nowait(self) -> T_Item:
        """
        Receive the next item if it can be done without waiting.

        :return: the received item
        :raises ~anyio.exceptions.ClosedResourceError: if this send stream has been closed
        :raises ~anyio.exceptions.EndOfStream: if the buffer is empty and this stream has been
            closed from the sending end
        :raises ~anyio.exceptions.WouldBlock: if there are no items in the buffer and no tasks
            waiting to send

        """
        if self._closed:
            raise ClosedResourceError

        if self._state.waiting_senders:
            # Get the item from the next sender
            send_event, item = self._state.waiting_senders.popitem(last=False)
            self._state.buffer.append(item)
            await send_event.set()

        if self._state.buffer:
            return self._state.buffer.popleft()
        elif not self._state.open_send_channels:
            raise EndOfStream

        raise WouldBlock

    async def receive(self) -> T_Item:
        await checkpoint()
        try:
            return await self.receive_nowait()
        except WouldBlock:
            # Add ourselves in the queue
            receive_event = create_event()
            container: List[T_Item] = []
            ticket = receive_event, container
            self._state.waiting_receivers.append(ticket)

            try:
                await receive_event.wait()
            except get_cancelled_exc_class():
                # If we already received an item in the container, pass it to the next receiver in
                # line
                index = self._state.waiting_receivers.index(ticket) + 1
                if container:
                    item = container[0]
                    while index < len(self._state.waiting_receivers):
                        receive_event, container = self._state.waiting_receivers[index]
                        if container:
                            item, container[0] = container[0], item
                        else:
                            # Found an untriggered receiver
                            container.append(item)
                            await receive_event.set()
                            break
                    else:
                        # Could not find an untriggered receiver, so in order to not lose any
                        # items, put it in the buffer, even if it exceeds the maximum buffer size
                        self._state.buffer.append(item)

                raise
            finally:
                self._state.waiting_receivers.remove(ticket)

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

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            self._state.open_receive_channels -= 1
            if self._state.open_receive_channels == 0:
                send_events = list(self._state.waiting_senders.keys())
                self._state.waiting_senders.clear()
                for event in send_events:
                    await event.set()


@dataclass
class MemoryObjectSendStream(Generic[T_Item], ObjectSendStream[T_Item]):
    _state: MemoryObjectStreamState[T_Item]
    _closed: bool = field(init=False, default=False)

    def __post_init__(self):
        self._state.open_send_channels += 1

    async def send_nowait(self, item: T_Item) -> None:
        """
        Send an item immediately if it can be done without waiting.

        :param item: the item to send
        :raises ~anyio.exceptions.ClosedResourceError: if this send stream has been closed
        :raises ~anyio.exceptions.BrokenResourceError: if the stream has been closed from the
            receiving end
        :raises ~anyio.exceptions.WouldBlock: if the buffer is full and there are no tasks waiting
            to receive

        """
        if self._closed:
            raise ClosedResourceError
        if not self._state.open_receive_channels:
            raise BrokenResourceError

        for receive_event, container in self._state.waiting_receivers:
            if not container:
                container.append(item)
                await receive_event.set()
                return

        if len(self._state.buffer) < self._state.max_buffer_size:
            self._state.buffer.append(item)
        else:
            raise WouldBlock

    async def send(self, item: T_Item) -> None:
        await checkpoint()
        try:
            await self.send_nowait(item)
        except WouldBlock:
            # Wait until there's someone on the receiving end
            send_event = create_event()
            self._state.waiting_senders[send_event] = item
            try:
                await send_event.wait()
            except BaseException:
                self._state.waiting_senders.pop(send_event, None)  # type: ignore[arg-type]
                raise

            if not self._state.open_receive_channels:
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

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            self._state.open_send_channels -= 1
            if self._state.open_send_channels == 0:
                receive_events = [event for event, container in self._state.waiting_receivers]
                for event in receive_events:
                    await event.set()
