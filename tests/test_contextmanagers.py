from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import AsyncExitStack, ExitStack

import pytest

from anyio import AsyncContextManagerMixin, ContextManagerMixin

pytestmark = pytest.mark.anyio


class DummyContextManager(ContextManagerMixin["DummyContextManager"]):
    def __init__(self, handle_exc: bool = False) -> None:
        self.started = False
        self.finished = False
        self.handle_exc = handle_exc

    def __contextmanager__(self) -> Generator[DummyContextManager, None, None]:
        self.started = True
        try:
            yield self
        except RuntimeError:
            if not self.handle_exc:
                raise

        self.finished = True


class DummyAsyncContextManager(AsyncContextManagerMixin["DummyAsyncContextManager"]):
    def __init__(self, handle_exc: bool = False) -> None:
        self.started = False
        self.finished = False
        self.handle_exc = handle_exc

    async def __asynccontextmanager__(
        self,
    ) -> AsyncGenerator[DummyAsyncContextManager, None]:
        self.started = True
        try:
            yield self
        except RuntimeError:
            if not self.handle_exc:
                raise

        self.finished = True


class TestContextManagerMixin:
    def test_contextmanager(self) -> None:
        with DummyContextManager() as cm:
            assert cm.started
            assert not cm.finished

        assert cm.finished

    @pytest.mark.parametrize("handle_exc", [True, False])
    def test_exception(self, handle_exc: bool) -> None:
        with ExitStack() as stack:
            if not handle_exc:
                stack.enter_context(pytest.raises(RuntimeError, match="^foo$"))

            cm = stack.enter_context(DummyContextManager(handle_exc))
            raise RuntimeError("foo")

        assert cm.started
        assert cm.finished == handle_exc

    def test_bad_return_type(self) -> None:
        class BadContextManager(ContextManagerMixin[None]):
            def __contextmanager__(self) -> Generator[None, None, None]:
                return self  # type: ignore[return-value]

        with pytest.raises(TypeError, match="did not return a generator object"):
            with BadContextManager():
                pass

    def test_no_initial_yield(self) -> None:
        class BadContextManager(ContextManagerMixin["BadContextManager"]):
            def __contextmanager__(self) -> Generator[BadContextManager, None, None]:
                if False:
                    yield self

        with pytest.raises(RuntimeError, match="generator returned without yielding"):
            with BadContextManager():
                pass

    def test_too_many_yields(self) -> None:
        class BadContextManager(ContextManagerMixin[None]):
            def __contextmanager__(self) -> Generator[None, None, None]:
                yield
                yield

        with pytest.raises(RuntimeError, match="generator didn't stop$"):
            with BadContextManager():
                pass


class TestAsyncContextManagerMixin:
    async def test_contextmanager(self) -> None:
        async with DummyAsyncContextManager() as cm:
            assert cm.started
            assert not cm.finished

        assert cm.finished

    @pytest.mark.parametrize("handle_exc", [True, False])
    async def test_exception(self, handle_exc: bool) -> None:
        async with AsyncExitStack() as stack:
            if not handle_exc:
                stack.enter_context(pytest.raises(RuntimeError, match="^foo$"))

            cm = await stack.enter_async_context(DummyAsyncContextManager(handle_exc))
            raise RuntimeError("foo")

        assert cm.started
        assert cm.finished == handle_exc

    async def test_bad_return_type(self) -> None:
        class BadContextManager(AsyncContextManagerMixin[None]):
            def __asynccontextmanager__(self) -> AsyncGenerator[None, None]:
                return None  # type: ignore[return-value]

        with pytest.raises(TypeError, match="did not return an async generator object"):
            async with BadContextManager():
                pass

    async def test_return_coroutine(self) -> None:
        class BadContextManager(AsyncContextManagerMixin[None]):
            async def __asynccontextmanager__(self) -> AsyncGenerator[None, None]:  # type: ignore[override]
                return None  # type: ignore[return-value]

        with pytest.raises(TypeError, match="returned a coroutine object instead of"):
            async with BadContextManager():
                pass

    async def test_no_initial_yield(self) -> None:
        class BadContextManager(AsyncContextManagerMixin[None]):
            async def __asynccontextmanager__(self) -> AsyncGenerator[None, None]:
                if False:
                    yield

        with pytest.raises(RuntimeError, match="generator returned without yielding"):
            async with BadContextManager():
                pass

    async def test_too_many_yields(self) -> None:
        class BadContextManager(AsyncContextManagerMixin[None]):
            async def __asynccontextmanager__(self) -> AsyncGenerator[None, None]:
                yield
                yield

        with pytest.raises(RuntimeError, match="generator didn't stop$"):
            async with BadContextManager():
                pass
