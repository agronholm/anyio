import ssl
import sys
from functools import wraps

from dataclasses import dataclass
from typing import Optional, Callable, Tuple, overload, List, Dict, Union, TypeVar, Any

from ..abc import ByteStream, AnyByteStream, Listener, TaskGroup
from .. import EndOfStream, BrokenResourceError

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

T_Retval = TypeVar('T_Retval')


@dataclass
class TLSStream(ByteStream):
    """
    A stream wrapper that encrypts all sent data and decrypts received data.

    This class has no public initializer; use :meth:`wrap` instead.

    :var AnyByteStream transport_stream: the wrapped stream
    :var bool standard_compatible: ``True`` if a closing handshake is expected from the peer and
        done from this side, ``False`` if not

    """
    transport_stream: AnyByteStream
    standard_compatible: bool
    _ssl_object: ssl.SSLObject
    _read_bio: ssl.MemoryBIO
    _write_bio: ssl.MemoryBIO

    @classmethod
    async def wrap(cls, transport_stream: AnyByteStream, *, server_side: Optional[bool] = None,
                   hostname: Optional[str] = None, ssl_context: Optional[ssl.SSLContext] = None,
                   standard_compatible: bool = True) -> 'TLSStream':
        """
        Wrap an existing stream with Transport Layer Security.

        This performs a TLS handshake with the peer.

        :param transport_stream: a bytes-transporting stream to wrap
        :param server_side: ``True`` if this is the server side of the connection, ``False`` if
            this is the client side (if omitted, will be set to ``False`` if ``hostname`` has been
            provided, ``False`` otherwise). Used only to create a default context when an explicit
            context has not been provided.
        :param hostname: host name of the peer (if host name checking is desired)
        :param ssl_context: the SSLContext object to use (if not provided, a secure default will be
            created)
        :param standard_compatible: if ``False``, skip the closing handshake when closing the
            connection, and don't raise an exception if the peer does the same
        :raises ~ssl.SSLError: if the TLS handshake fails

        """
        if server_side is None:
            server_side = not hostname

        if not ssl_context:
            purpose = ssl.Purpose.CLIENT_AUTH if server_side else ssl.Purpose.SERVER_AUTH
            ssl_context = ssl.create_default_context(purpose)

        bio_in = ssl.MemoryBIO()
        bio_out = ssl.MemoryBIO()
        ssl_object = ssl_context.wrap_bio(bio_in, bio_out, server_side=server_side,
                                          server_hostname=hostname)
        wrapper = cls(transport_stream=transport_stream,
                      standard_compatible=standard_compatible, _ssl_object=ssl_object,
                      _read_bio=bio_in, _write_bio=bio_out)
        await wrapper._call_sslobject_method(ssl_object.do_handshake)
        return wrapper

    async def _call_sslobject_method(self, func: Callable[..., T_Retval], *args) -> T_Retval:
        while True:
            try:
                result = func(*args)
            except ssl.SSLWantReadError:
                try:
                    # Flush any pending writes first
                    if self._write_bio.pending:
                        await self.transport_stream.send(self._write_bio.read())

                    data = await self.transport_stream.receive()
                except EndOfStream:
                    self._read_bio.write_eof()
                except OSError as exc:
                    self._read_bio.write_eof()
                    self._write_bio.write_eof()
                    raise BrokenResourceError from exc
                else:
                    self._read_bio.write(data)
            except ssl.SSLWantWriteError:
                await self.transport_stream.send(self._write_bio.read())
            except (ssl.SSLEOFError, ssl.SSLSyscallError) as exc:
                raise BrokenResourceError from exc
            else:
                # Flush any pending writes first
                if self._write_bio.pending:
                    await self.transport_stream.send(self._write_bio.read())

                return result

    async def unwrap(self) -> Tuple[AnyByteStream, bytes]:
        """
        Does the TLS closing handshake.

        :return: a tuple of (wrapped byte stream, bytes left in the read buffer)

        """
        await self._call_sslobject_method(self._ssl_object.unwrap)
        self._read_bio.write_eof()
        self._write_bio.write_eof()
        return self.transport_stream, self._read_bio.read()

    async def aclose(self) -> None:
        if self.standard_compatible:
            try:
                await self.unwrap()
            except BaseException:
                from .. import aclose_forcefully
                await aclose_forcefully(self.transport_stream)
                raise

        await self.transport_stream.aclose()

    async def receive(self, max_bytes: int = 65536) -> bytes:
        return await self._call_sslobject_method(self._ssl_object.read, max_bytes)

    async def send(self, item: bytes) -> None:
        await self._call_sslobject_method(self._ssl_object.write, item)

    async def send_eof(self) -> None:
        version_tuple = tuple(int(part) for part in self.tls_version.split('.'))
        if version_tuple < (1, 3):
            raise NotImplementedError(f'send_eof() requires at least TLS v1.3; current session '
                                      f'uses {self.tls_version}')

        raise NotImplementedError('send_eof() has not yet been implemented for TLS streams')

    @property
    def alpn_protocol(self) -> Optional[str]:
        return self._ssl_object.selected_alpn_protocol()  # type: ignore

    def get_channel_binding(self, cb_type: str = 'tls-unique') -> bytes:
        return self._ssl_object.get_channel_binding(cb_type)  # type: ignore

    @property
    def tls_version(self) -> str:
        return self._ssl_object.version()  # type: ignore

    @property
    def cipher(self) -> Tuple[str, str, int]:
        return self._ssl_object.cipher()  # type: ignore

    @property
    def shared_ciphers(self) -> List[Tuple[str, str, int]]:
        return self._ssl_object.shared_ciphers()  # type: ignore

    @property
    def server_hostname(self) -> Optional[str]:
        return self._ssl_object.server_hostname

    @property
    def server_side(self) -> bool:
        return self._ssl_object.server_side

    @overload
    def getpeercert(self, binary_form: Literal[False] = False) -> Dict[str, Union[str, tuple]]:
        ...

    @overload
    def getpeercert(self, binary_form: Literal[True]) -> bytes:
        ...

    def getpeercert(self, binary_form: bool = False) -> Union[Dict[str, Union[str, tuple]], bytes,
                                                              None]:
        return self._ssl_object.getpeercert(binary_form)


@dataclass
class TLSListener(Listener[TLSStream]):
    """
    A convenience listener that wraps another listener and auto-negotiates a TLS session on every
    accepted connection.

    :param Listener listener: the listener to wrap
    :param ssl_context: the SSL context object
    :param standard_compatible: a flag passed through to :meth:`TLSStream.wrap`
    """

    listener: Listener
    ssl_context: ssl.SSLContext
    standard_compatible: bool = True

    async def serve(self, handler: Callable[[TLSStream], Any],
                    task_group: Optional[TaskGroup] = None) -> None:
        @wraps(handler)
        async def handler_wrapper(stream: AnyByteStream):
            wrapped_stream = await TLSStream.wrap(stream, ssl_context=self.ssl_context,
                                                  standard_compatible=self.standard_compatible)
            await handler(wrapped_stream)

        await self.listener.serve(handler_wrapper, task_group)

    async def aclose(self) -> None:
        await self.listener.aclose()
