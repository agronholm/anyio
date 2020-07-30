from dataclasses import dataclass, field

from ..abc import AnyByteReceiveStream, ByteReceiveStream
from ..exceptions import IncompleteRead, DelimiterNotFound, EndOfStream, ClosedResourceError


@dataclass
class BufferedByteReceiveStream(ByteReceiveStream):
    """
    Wraps any bytes-based receive stream and uses a buffer to provide sophisticated receiving
    capabilities in the form of a byte stream.
    """

    receive_stream: AnyByteReceiveStream
    _buffer: bytearray = field(init=False, default_factory=bytearray)
    _closed: bool = field(init=False, default=False)

    async def aclose(self) -> None:
        await self.receive_stream.aclose()
        self._closed = True

    @property
    def buffer(self) -> bytes:
        return bytes(self._buffer)

    async def receive(self, max_bytes: int = 65536) -> bytes:
        if self._closed:
            raise ClosedResourceError

        if self._buffer:
            chunk = bytes(self._buffer[:max_bytes])
            del self._buffer[:max_bytes]
            return chunk
        elif isinstance(self.receive_stream, ByteReceiveStream):
            return await self.receive_stream.receive(max_bytes)
        else:
            # With a bytes-oriented object stream, we need to handle any surplus bytes we get from
            # the receive() call
            try:
                chunk = await self.receive_stream.receive()
            except EndOfStream:
                return b''

            if len(chunk) > max_bytes:
                # Save the surplus bytes in the buffer
                self._buffer.extend(chunk[max_bytes:])
                return chunk[:max_bytes]
            else:
                return chunk

    async def receive_exactly(self, nbytes: int) -> bytes:
        """
        Read exactly the given amount of bytes from the stream.

        :param nbytes: the number of bytes to read
        :return: the bytes read
        :raises anyio.exceptions.IncompleteRead: if the stream was closed before the requested
            amount of bytes could be read from the stream

        """
        while True:
            remaining = nbytes - len(self._buffer)
            if remaining <= 0:
                retval = self._buffer[:nbytes]
                del self._buffer[:nbytes]
                return retval

            try:
                if isinstance(self.receive_stream, ByteReceiveStream):
                    chunk = await self.receive_stream.receive(remaining)
                else:
                    chunk = await self.receive_stream.receive()
            except EndOfStream:
                chunk = b''

            if not chunk:
                raise IncompleteRead

            self._buffer.extend(chunk)

    async def receive_until(self, delimiter: bytes, max_bytes: int) -> bytes:
        """
        Read from the stream until the delimiter is found or max_bytes have been read.

        :param delimiter: the marker to look for in the stream
        :param max_bytes: maximum number of bytes that will be read before raising
            :exc:`~anyio.exceptions.DelimiterNotFound`
        :return: the bytes read, including the delimiter
        :raises anyio.exceptions.IncompleteRead: if the stream was closed before the delimiter
            was found
        :raises anyio.exceptions.DelimiterNotFound: if the delimiter is not found within the
            bytes read up to the maximum allowed

        """
        delimiter_size = len(delimiter)
        offset = 0
        while True:
            # Check if the delimiter can be found in the current buffer
            index = self._buffer.find(delimiter, offset)
            if index >= 0:
                found = self._buffer[:index]
                del self._buffer[:index + len(delimiter):]
                return found

            # Check if the buffer is already at or over the limit
            if len(self._buffer) >= max_bytes:
                raise DelimiterNotFound(max_bytes)

            # Read more data into the buffer from the socket
            try:
                data = await self.receive_stream.receive()
            except EndOfStream:
                data = b''

            if not data:
                raise IncompleteRead

            # Move the offset forward and add the new data to the buffer
            offset = max(len(self._buffer) - delimiter_size + 1, 0)
            self._buffer.extend(data)
