Context manager mix-in classes
==============================

.. py:currentmodule:: anyio

Python classes that want to offer context management functionality normally implement
``__enter__()`` and ``__exit__()`` (for synchronous context managers) or
``__aenter__()`` and ``__aexit__()`` (for asynchronous context managers). While this
offers precise control and re-entrancy support, embedding _other_ context managers in
this logic can be very error prone. To make this easier, AnyIO provides two context
manager mix-in classes, :class:`ContextManagerMixin` and
:class:`AsyncContextManagerMixin`. These classes provide implementations of
``__enter__()``, ``__exit__()`` or ``__aenter__()``, and ``__aexit__()``, that provide
another way to implement context managers similar to
:func:`@contextmanager <contextlib.contextmanager>` and
:func:`@asynccontextmanager <contextlib.asynccontextmanager>` - a generator-based
approach where the ``yield`` statement signals that the context has been entered.

Here's a trivial example of how to use the mix-in classes:

.. tabs::

   .. code-tab:: python Synchronous

      from collections.abc import Generator
      from contextlib import contextmanager
      from typing import Self

      from anyio import ContextManagerMixin

      class MyContextManager(ContextManagerMixin):
          @contextmanager
          def __contextmanager__(self) -> Generator[Self]:
              print("entering context")
              yield self
              print("exiting context")

   .. code-tab:: python Asynchronous

      from collections.abc import AsyncGenerator
      from contextlib import asynccontextmanager
      from typing import Self

      from anyio import AsyncContextManagerMixin

      class MyAsyncContextManager(AsyncContextManagerMixin):
          @asynccontextmanager
          async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
              print("entering context")
              yield self
              print("exiting context")

When should I use the contextmanager mix-in classes?
----------------------------------------------------

When embedding other context managers, a common mistake is forgetting about error
handling when entering the context. Consider this example::

    from typing import Self

    from anyio import create_task_group

    class MyBrokenContextManager:
        async def __aenter__(self) -> Self:
            self._task_group = await create_task_group().__aenter__()
            # BOOM: missing the "arg" argument here to my_background_func!
            self._task_group.start_soon(self.my_background_func)
            return self

        async def __aexit__(self, exc_type, exc_value, traceback) -> bool | None:
            return await self._task_group.__aexit__(exc_type, exc_value, traceback)

        async my_background_func(self, arg: int) -> None:
            ...

It's easy to think that you have everything covered with ``__aexit__()`` here, but what
if something goes wrong in ``__aenter__()``?  The ``__aexit__()`` method will never be
called.

The mix-in classes solve this problem by providing a robust implementation of
``__enter__()``/``__exit__()`` or ``__aenter__()``/``__aexit__()`` that handles errors
correctly. Thus, the above code should be written as::

    from collections.abc import AsyncGenerator
    from contextlib import asynccontextmanager
    from typing import Self

    from anyio import AsyncContextManagerMixin, create_task_group

    class MyBetterContextManager(AsyncContextManagerMixin):
        @asynccontextmanager
        async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
            async with create_task_group() as task_group:
                # Still crashes, but at least now the task group is exited
                task_group.start_soon(self.my_background_func)
                yield self

        async my_background_func(self, arg: int) -> None:
            ...

.. seealso:: :ref:`cancel_scope_stack_corruption`

Inheriting context manager classes
----------------------------------

Here's how you would call the superclass implementation from a subclass:

.. tabs::

   .. code-tab:: python Synchronous

      from collections.abc import Generator
      from contextlib import contextmanager
      from typing import Self

      from anyio import ContextManagerMixin

      class SuperclassContextManager(ContextManagerMixin):
          @contextmanager
          def __contextmanager__(self) -> Generator[Self]:
              print("superclass entered")
              try:
                  yield self
              finally:
                  print("superclass exited")


      class SubclassContextManager(SuperclassContextManager):
          @contextmanager
          def __contextmanager__(self) -> Generator[Self]:
              print("subclass entered")
              try:
                  with super().__contextmanager__():
                      yield self
              finally:
                  print("subclass exited")

   .. code-tab:: python Asynchronous

      from collections.abc import AsyncGenerator
      from contextlib import asynccontextmanager
      from typing import Self

      from anyio import AsyncContextManagerMixin

      class SuperclassContextManager(AsyncContextManagerMixin):
          @asynccontextmanager
          async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
              print("superclass entered")
              try:
                  yield self
              finally:
                  print("superclass exited")


      class SubclassContextManager(SuperclassContextManager):
          @asynccontextmanager
          async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
              print("subclass entered")
              try:
                  async with super().__asynccontextmanager__():
                      yield self
              finally:
                  print("subclass exited")
