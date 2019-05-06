import errno
import socket
import ssl
from abc import ABCMeta, abstractmethod
from ipaddress import ip_address
from typing import Union, Tuple, Any, Optional, Callable, Dict, List, cast

from async_generator import async_generator, yield_

from . import abc
from .abc import IPAddressType
from .exceptions import DelimiterNotFound, IncompleteRead, TLSRequired, ClosedResourceError


class BaseSocket(metaclass=ABCMeta):
    __slots__ = '_raw_socket'

    def __init__(self, raw_socket: socket.SocketType) -> None:
        self._raw_socket = raw_socket
        self._raw_socket.setblocking(False)

    def __getattr__(self, item):
        return getattr(self._raw_socket, item)

    @abstractmethod
    async def _wait_readable(self) -> None:
        pass

    @abstractmethod
    async def _wait_writable(self) -> None:
        pass

    @abstractmethod
    async def _notify_close(self) -> None:
        pass

    @abstractmethod
    async def _check_cancelled(self) -> None:
        pass

    @abstractmethod
    async def _run_in_thread(self, func: Callable, *args):
        pass

    async def accept(self):
        await self._check_cancelled()
        try:
            raw_socket, address = self._raw_socket.accept()
        except BlockingIOError:
            await self._wait_readable()
            raw_socket, address = self._raw_socket.accept()

        if raw_socket.family == socket.AF_INET:
            raw_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        return self.__class__(raw_socket), address

    async def bind(self, address: Union[Tuple[str, int], str]) -> None:
        await self._check_cancelled()
        if isinstance(address, tuple) and len(address) == 2:
            # For IP address/port combinations, call bind() directly
            try:
                ip_address(address[0])
            except ValueError:
                pass
            else:
                self._raw_socket.bind(address)
                return

        # In all other cases, do this in a worker thread to avoid blocking the event loop thread
        await self._run_in_thread(self._raw_socket.bind, address)

    async def close(self):
        await self._notify_close()
        self._raw_socket.close()

    async def connect(self, address: Union[tuple, str, bytes]) -> None:
        await self._check_cancelled()
        try:
            self._raw_socket.connect(address)
        except BlockingIOError:
            await self._wait_writable()

        error = self._raw_socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if error:
            raise OSError(error, errno.errorcode[error])

    async def recv(self, size: int, *, flags: int = 0) -> bytes:
        while True:
            await self._check_cancelled()
            try:
                return self._raw_socket.recv(size, flags)
            except (BlockingIOError, ssl.SSLWantReadError):
                await self._wait_readable()
            except ssl.SSLWantWriteError:
                await self._wait_writable()
            except ssl.SSLEOFError:
                self._raw_socket.close()
                raise

    async def recv_into(self, buffer, nbytes: int, *, flags: int = 0) -> int:
        while True:
            await self._check_cancelled()
            try:
                return self._raw_socket.recv_into(buffer, nbytes, flags)
            except (BlockingIOError, ssl.SSLWantReadError):
                await self._wait_readable()
            except ssl.SSLWantWriteError:
                await self._wait_writable()

    async def recvfrom(self, size: int, *, flags: int = 0) -> Tuple[bytes, Any]:
        await self._check_cancelled()
        try:
            return self._raw_socket.recvfrom(size, flags)
        except BlockingIOError:
            await self._wait_readable()
            return self._raw_socket.recvfrom(size, flags)

    async def recvfrom_into(self, buffer, size: int, *, flags: int = 0):
        await self._check_cancelled()
        try:
            return self._raw_socket.recvfrom_into(buffer, size, flags)
        except BlockingIOError:
            await self._wait_readable()
            return self._raw_socket.recvfrom_into(buffer, size, flags)

    async def send(self, data: bytes, *, flags: int = 0) -> int:
        while True:
            await self._check_cancelled()
            try:
                return self._raw_socket.send(data, flags)
            except (BlockingIOError, ssl.SSLWantWriteError):
                await self._wait_writable()
            except ssl.SSLWantReadError:
                await self._wait_readable()

    async def sendto(self, data: bytes, addr, *, flags: int = 0) -> int:
        await self._check_cancelled()
        try:
            return self._raw_socket.sendto(data, flags, addr)
        except BlockingIOError:
            await self._wait_writable()
            return self._raw_socket.sendto(data, flags, addr)

    async def sendall(self, data: bytes, *, flags: int = 0) -> None:
        offset = 0
        total = len(data)
        buffer = memoryview(data)
        while offset < total:
            await self._check_cancelled()
            try:
                offset += self._raw_socket.send(buffer[offset:], flags)
            except (BlockingIOError, ssl.SSLWantWriteError):
                await self._wait_writable()
            except ssl.SSLWantReadError:
                await self._wait_readable()
            except ssl.SSLEOFError:
                self._raw_socket.close()
                raise

    async def start_tls(self, context: ssl.SSLContext,
                        server_hostname: Optional[str] = None,
                        suppress_ragged_eofs: bool = False) -> None:
        plain_socket = self._raw_socket
        self._raw_socket = context.wrap_socket(
            self._raw_socket, server_side=not server_hostname, do_handshake_on_connect=False,
            server_hostname=server_hostname, suppress_ragged_eofs=suppress_ragged_eofs)
        while True:
            try:
                self._raw_socket.do_handshake()
                return
            except ssl.SSLWantReadError:
                await self._wait_readable()
            except ssl.SSLWantWriteError:
                await self._wait_writable()
            except BaseException:
                self._raw_socket = plain_socket
                raise

    async def unwrap_tls(self) -> None:
        if isinstance(self._raw_socket, ssl.SSLSocket):
            while True:
                try:
                    self._raw_socket = cast(ssl.SSLSocket, self._raw_socket).unwrap()
                    return
                except ssl.SSLWantReadError:
                    await self._wait_readable()
                except ssl.SSLWantWriteError:
                    await self._wait_writable()
                except OSError as exc:
                    if exc.errno == 0:
                        # https://bugs.python.org/issue10808
                        self._raw_socket.close()
                        return
                    else:
                        raise


class SocketStream(abc.SocketStream):
    def __init__(self, sock: BaseSocket, ssl_context: Optional[ssl.SSLContext] = None,
                 server_hostname: Optional[str] = None,
                 tls_standard_compatible: bool = True) -> None:
        self._socket = sock
        self._ssl_context = ssl_context
        self._server_hostname = server_hostname
        self._tls_standard_compatible = tls_standard_compatible
        self._buffer = b''

    async def close(self):
        from . import move_on_after

        try:
            if self._tls_standard_compatible and self._socket.fileno() != -1:
                async with move_on_after(5, shield=True):
                    await self._socket.unwrap_tls()
        finally:
            await self._socket.close()

    def getsockopt(self, level, optname, *args):
        return self._socket.getsockopt(level, optname, *args)

    def setsockopt(self, level, optname, value, *args) -> None:
        self._socket.setsockopt(level, optname, value, *args)

    @property
    def buffered_data(self) -> bytes:
        return self._buffer

    async def receive_some(self, max_bytes: int) -> bytes:
        if self._buffer:
            data, self._buffer = self._buffer[:max_bytes], self._buffer[max_bytes:]
            return data

        return await self._socket.recv(max_bytes)

    async def receive_exactly(self, nbytes: int) -> bytes:
        bytes_left = nbytes - len(self._buffer)
        while bytes_left > 0:
            chunk = await self._socket.recv(nbytes)
            if not chunk:
                raise IncompleteRead

            self._buffer += chunk
            bytes_left -= len(chunk)

        result = self._buffer[:nbytes]
        self._buffer = self._buffer[nbytes:]
        return result

    async def receive_until(self, delimiter: bytes, max_size: int) -> bytes:
        delimiter_size = len(delimiter)
        offset = 0
        while True:
            # Check if the delimiter can be found in the current buffer
            index = self._buffer.find(delimiter, offset)
            if index >= 0:
                found = self._buffer[:index]
                self._buffer = self._buffer[index + len(delimiter):]
                return found

            # Check if the buffer is already at or over the limit
            if len(self._buffer) >= max_size:
                raise DelimiterNotFound(max_size)

            # Read more data into the buffer from the socket
            read_size = max_size - len(self._buffer)
            data = await self._socket.recv(read_size)
            if not data:
                raise IncompleteRead

            # Move the offset forward and add the new data to the buffer
            offset = max(len(self._buffer) - delimiter_size + 1, 0)
            self._buffer += data

    @async_generator
    async def receive_chunks(self, max_size: int):
        while True:
            data = await self.receive_some(max_size)
            if data:
                await yield_(data)
            else:
                break

    @async_generator
    async def receive_delimited_chunks(self, delimiter: bytes, max_chunk_size: int):
        while True:
            try:
                chunk = await self.receive_until(delimiter, max_chunk_size)
            except IncompleteRead:
                if self._buffer:
                    raise
                else:
                    break

            await yield_(chunk)

    async def send_all(self, data: bytes) -> None:
        return await self._socket.sendall(data)

    #
    # TLS methods
    #

    def _call_sslsocket_method(self, name: str, *args):
        try:
            method = getattr(self._socket, name)
        except AttributeError:
            raise TLSRequired from None

        return method(*args)

    async def start_tls(self, context: Optional[ssl.SSLContext] = None) -> None:
        ssl_context = context or self._ssl_context or ssl.create_default_context()
        await self._socket.start_tls(ssl_context, self._server_hostname,
                                     not self._tls_standard_compatible)

    def getpeercert(self, binary_form: bool = False) -> Union[Dict[str, Union[str, tuple]],
                                                              bytes, None]:
        return self._call_sslsocket_method('getpeercert', binary_form)

    @property
    def alpn_protocol(self) -> Optional[str]:
        return self._call_sslsocket_method('selected_alpn_protocol')

    def get_channel_binding(self, cb_type: str = 'tls-unique') -> bytes:
        return self._call_sslsocket_method('get_channel_binding', cb_type)

    @property
    def tls_version(self) -> Optional[str]:
        try:
            return self._call_sslsocket_method('version')
        except TLSRequired:
            return None

    @property
    def cipher(self) -> Tuple[str, str, int]:
        return self._call_sslsocket_method('cipher')

    @property
    def shared_ciphers(self) -> List[Tuple[str, str, int]]:
        return self._call_sslsocket_method('shared_ciphers')

    @property
    def server_hostname(self) -> str:
        try:
            return self._socket.server_hostname
        except AttributeError:
            raise TLSRequired from None

    @property
    def server_side(self) -> bool:
        try:
            return self._socket.server_side
        except AttributeError:
            raise TLSRequired from None


class SocketStreamServer(abc.SocketStreamServer):
    __slots__ = '_socket', '_ssl_context', '_autostart_tls'

    def __init__(self, sock: BaseSocket, ssl_context: Optional[ssl.SSLContext],
                 autostart_tls: bool, tls_standard_compatible: bool) -> None:
        self._socket = sock
        self._ssl_context = ssl_context
        self._autostart_tls = autostart_tls
        self._tls_standard_compatible = tls_standard_compatible

    async def close(self) -> None:
        await self._socket.close()

    def getsockopt(self, level, optname, *args):
        return self._socket.getsockopt(level, optname, *args)

    def setsockopt(self, level, optname, value, *args) -> None:
        self._socket.setsockopt(level, optname, value, *args)

    @property
    def address(self) -> Union[Tuple[str, int], Tuple[str, int, int, int], str]:
        return self._socket.getsockname()

    @property
    def port(self) -> int:
        address = self._socket.getsockname()
        if isinstance(address, tuple):
            return cast(int, self.address[1])
        else:
            raise ValueError('Not a TCP socket')

    async def accept(self):
        sock, addr = await self._socket.accept()
        try:
            stream = SocketStream(sock, self._ssl_context, None, self._tls_standard_compatible)
            if self._ssl_context and self._autostart_tls:
                await stream.start_tls()

            return stream
        except BaseException:
            await sock.close()
            raise

    @async_generator
    async def accept_connections(self):
        while self._socket.fileno() != -1:
            try:
                await yield_(await self.accept())
            except ClosedResourceError:
                break


class UDPSocket(abc.UDPSocket):
    __slots__ = '_socket'

    def __init__(self, sock: BaseSocket) -> None:
        self._socket = sock

    async def close(self):
        await self._socket.close()

    @property
    def address(self) -> Union[Tuple[str, int], Tuple[str, int, int, int]]:
        return self._socket.getsockname()

    @property
    def port(self) -> int:
        return self.address[1]

    def getsockopt(self, level, optname, *args):
        return self._socket.getsockopt(level, optname, *args)

    def setsockopt(self, level, optname, value, *args) -> None:
        self._socket.setsockopt(level, optname, value, *args)

    async def receive(self, max_bytes: int) -> Tuple[bytes, str]:
        return await self._socket.recvfrom(max_bytes)

    @async_generator
    async def receive_packets(self, max_size: int):
        while self._socket.fileno() != -1:
            packet, address = await self.receive(max_size)
            if packet:
                await yield_((packet, address))
            else:
                break

    async def send(self, data: bytes, address: Optional[IPAddressType] = None,
                   port: Optional[int] = None) -> None:
        if address is not None and port is not None:
            await self._socket.sendto(data, (str(address), port))
        else:
            await self._socket.send(data)
