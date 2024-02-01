Using typed attributes
======================

.. py:currentmodule:: anyio

On AnyIO, streams and listeners can be layered on top of each other to provide extra
functionality. But when you want to look up information from one of the layers down
below, you might have to traverse the entire chain to find what you're looking for,
which is highly inconvenient. To address this, AnyIO has a system of *typed attributes*
where you can look for a specific attribute by its unique key. If a stream or listener
wrapper does not have the attribute you're looking for, it will look it up in the
wrapped instance, and that wrapper can look in its wrapped instance and so on, until the
attribute is either found or the end of the chain is reached. This also lets wrappers
override attributes from the wrapped objects when necessary.

A common use case is finding the IP address of the remote side of a TCP connection when
the stream may be either :class:`~.abc.SocketStream` or
:class:`~.streams.tls.TLSStream`::

    from anyio import connect_tcp
    from anyio.abc import SocketAttribute


    async def connect(host, port, tls: bool):
        stream = await connect_tcp(host, port, tls=tls)
        print('Connected to', stream.extra(SocketAttribute.remote_address))

Each typed attribute provider class should document the set of attributes it provides on
its own.

Defining your own typed attributes
----------------------------------

By convention, typed attributes are stored together in a container class with other
attributes of the same category::

    from anyio import TypedAttributeSet, typed_attribute


    class MyTypedAttribute(TypedAttributeSet):
        string_valued_attribute: str = typed_attribute()
        some_float_attribute: float = typed_attribute()

To provide values for these attributes, implement the
:meth:`~.TypedAttributeProvider.extra_attributes` property in your class::

    from collections.abc import Callable, Mapping

    from anyio import TypedAttributeProvider


    class MyAttributeProvider(TypedAttributeProvider):
        @property
        def extra_attributes() -> Mapping[Any, Callable[[], Any]]:
            return {
                MyTypedAttribute.string_valued_attribute: lambda: 'my attribute value',
                MyTypedAttribute.some_float_attribute: lambda: 6.492
            }

If your class inherits from another typed attribute provider, make sure you include its
attributes in the return value::

    class AnotherAttributeProvider(MyAttributeProvider):
        @property
        def extra_attributes() -> Mapping[Any, Callable[[], Any]]:
            return {
                **super().extra_attributes,
                MyTypedAttribute.string_valued_attribute: lambda: 'overridden attribute value'
            }
