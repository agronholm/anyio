from __future__ import annotations

import sys
from collections.abc import AsyncGenerator, Generator
from contextlib import (
    AbstractContextManager,
    AsyncExitStack,
    ExitStack,
    asynccontextmanager,
    contextmanager,
)

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

import pytest

from anyio import (
    AsyncContextManagerMixin,
    CancelScope,
    ContextManagerMixin,
    Event,
    create_task_group,
)
from anyio.lowlevel import checkpoint


class DummyContextManager(ContextManagerMixin):
    def __init__(self, handle_exc: bool = False) -> None:
        self.started = False
        self.finished = False
        self.handle_exc = handle_exc

    @contextmanager
    def __contextmanager__(self) -> Generator[Self]:
        self.started = True
        try:
            yield self
        except RuntimeError:
            if not self.handle_exc:
                raise

        self.finished = True


class DummyAsyncContextManager(AsyncContextManagerMixin):
    def __init__(self, handle_exc: bool = False) -> None:
        self.started = False
        self.finished = False
        self.handle_exc = handle_exc

    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
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

    def test_return_bad_type(self) -> None:
        class BadContextManager(ContextManagerMixin):
            def __contextmanager__(self) -> AbstractContextManager[None]:
                return None  # type: ignore[return-value]

        with pytest.raises(TypeError, match="did not return a context manager"):
            with BadContextManager():
                pass

    def test_return_generator(self) -> None:
        class BadContextManager(ContextManagerMixin):
            def __contextmanager__(self):  # type: ignore[no-untyped-def]
                yield self

        with pytest.raises(TypeError, match="returned a generator"):
            with BadContextManager():
                pass

    def test_return_self(self) -> None:
        class BadContextManager(ContextManagerMixin):
            def __contextmanager__(self):  # type: ignore[no-untyped-def]
                return self

        with pytest.raises(TypeError, match="returned self"):
            with BadContextManager():
                pass

    def test_enter_twice(self) -> None:
        with (
            DummyContextManager() as cm,
            pytest.raises(
                RuntimeError,
                match="^this DummyContextManager has already been entered$",
            ),
            cm,
        ):
            pass

    def test_exit_before_enter(self) -> None:
        cm = DummyContextManager()
        with pytest.raises(
            RuntimeError, match="^this DummyContextManager has not been entered yet$"
        ):
            cm.__exit__(None, None, None)

    @pytest.mark.parametrize("when", ["enter", "exit"])
    def test_reenter_during_transition(self, when: str) -> None:
        reenter = True

        class ReentrantContextManager(ContextManagerMixin):
            @contextmanager
            def __contextmanager__(self) -> Generator[None]:
                nonlocal reenter
                if not reenter:
                    yield
                    return

                reenter = False
                if when == "enter":
                    with pytest.raises(RuntimeError, match="has already been entered"):
                        with self:
                            pass

                yield

                if when == "exit":
                    with pytest.raises(RuntimeError, match="has already been entered"):
                        with self:
                            pass

        cm = ReentrantContextManager()
        with cm:
            pass

        with cm:
            pass

    @pytest.mark.parametrize("when", ["enter", "exit"])
    def test_reuse_after_transition_error(self, when: str) -> None:
        error = BaseException("transition failed")
        fail = True

        class FailingContextManager(ContextManagerMixin):
            @contextmanager
            def __contextmanager__(self) -> Generator[None]:
                if fail and when == "enter":
                    raise error

                yield

                if fail and when == "exit":
                    raise error

        cm = FailingContextManager()
        with pytest.raises(BaseException) as exc:
            with cm:
                pass

        assert exc.value is error
        fail = False
        with cm:
            pass

    def test_call_superclass_method(self) -> None:
        class InheritedContextManager(DummyContextManager):
            def __init__(self, handle_exc: bool = False) -> None:
                super().__init__(handle_exc)
                self.child_started = False
                self.child_finished = False

            @contextmanager
            def __contextmanager__(self) -> Generator[Self]:
                self.child_started = True
                with super().__contextmanager__():
                    assert self.started
                    try:
                        yield self
                    except RuntimeError:
                        if not self.handle_exc:
                            raise

                assert self.finished
                self.child_finished = True

        with InheritedContextManager() as cm:
            assert cm.started
            assert not cm.finished
            assert cm.child_started
            assert not cm.child_finished

        assert cm.finished
        assert cm.child_finished


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

    async def test_return_bad_type(self) -> None:
        class BadContextManager(AsyncContextManagerMixin):
            def __asynccontextmanager__(self):  # type: ignore[no-untyped-def]
                return None

        with pytest.raises(TypeError, match="did not return an async context manager"):
            async with BadContextManager():
                pass

    async def test_return_async_generator(self) -> None:
        class BadContextManager(AsyncContextManagerMixin):
            async def __asynccontextmanager__(self):  # type: ignore[no-untyped-def]
                yield self

        with pytest.raises(TypeError, match="returned an async generator"):
            async with BadContextManager():
                pass

    async def test_return_self(self) -> None:
        class BadContextManager(AsyncContextManagerMixin):
            def __asynccontextmanager__(self):  # type: ignore[no-untyped-def]
                return self

        with pytest.raises(TypeError, match="returned self"):
            async with BadContextManager():
                pass

    async def test_return_coroutine(self) -> None:
        class BadContextManager(AsyncContextManagerMixin):
            async def __asynccontextmanager__(self):  # type: ignore[no-untyped-def,override]
                return self

        with pytest.raises(TypeError, match="returned a coroutine object instead of"):
            async with BadContextManager():  # type: ignore[misc]
                pass

    async def test_enter_twice(self) -> None:
        async with DummyAsyncContextManager() as cm:
            with pytest.raises(
                RuntimeError,
                match="^this DummyAsyncContextManager has already been entered$",
            ):
                async with cm:
                    pass

    async def test_exit_before_enter(self) -> None:
        cm = DummyAsyncContextManager()
        with pytest.raises(
            RuntimeError,
            match="^this DummyAsyncContextManager has not been entered yet$",
        ):
            await cm.__aexit__(None, None, None)

    @pytest.mark.parametrize("when", ["enter", "exit"])
    async def test_concurrent_entry_during_transition(self, when: str) -> None:
        started = Event()
        resume = Event()
        pause = True

        class SlowAsyncContextManager(AsyncContextManagerMixin):
            @asynccontextmanager
            async def __asynccontextmanager__(self) -> AsyncGenerator[None]:
                nonlocal pause
                if not pause:
                    yield
                    return

                pause = False
                if when == "enter":
                    started.set()
                    await resume.wait()

                yield

                if when == "exit":
                    started.set()
                    await resume.wait()

        cm = SlowAsyncContextManager()

        async def use_context_manager() -> None:
            async with cm:
                pass

        async with create_task_group() as tg:
            tg.start_soon(use_context_manager)
            await started.wait()
            try:
                with pytest.raises(RuntimeError, match="has already been entered"):
                    async with cm:
                        pass
            finally:
                resume.set()

        async with cm:
            pass

    @pytest.mark.parametrize("when", ["enter", "exit"])
    async def test_reuse_after_transition_error(self, when: str) -> None:
        error = BaseException("transition failed")
        fail = True

        class FailingAsyncContextManager(AsyncContextManagerMixin):
            @asynccontextmanager
            async def __asynccontextmanager__(self) -> AsyncGenerator[None]:
                if fail and when == "enter":
                    raise error

                yield

                if fail and when == "exit":
                    raise error

        cm = FailingAsyncContextManager()
        with pytest.raises(BaseException) as exc:
            async with cm:
                pass

        assert exc.value is error
        fail = False
        async with cm:
            pass

    @pytest.mark.parametrize("when", ["enter", "exit"])
    async def test_reuse_after_transition_cancelled(self, when: str) -> None:
        class CancelledAsyncContextManager(AsyncContextManagerMixin):
            @asynccontextmanager
            async def __asynccontextmanager__(self) -> AsyncGenerator[None]:
                if when == "enter":
                    await checkpoint()

                yield

                if when == "exit":
                    await checkpoint()

        cm = CancelledAsyncContextManager()
        with CancelScope() as scope:
            if when == "enter":
                scope.cancel()

            async with cm:
                scope.cancel()

        assert scope.cancelled_caught
        async with cm:
            pass

    async def test_call_superclass_method(self) -> None:
        class InheritedAsyncContextManager(DummyAsyncContextManager):
            def __init__(self, handle_exc: bool = False) -> None:
                super().__init__(handle_exc)
                self.child_started = False
                self.child_finished = False

            @asynccontextmanager
            async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
                self.child_started = True
                async with super().__asynccontextmanager__():
                    assert self.started
                    try:
                        yield self
                    except RuntimeError:
                        if not self.handle_exc:
                            raise

                assert self.finished
                self.child_finished = True

        async with InheritedAsyncContextManager() as cm:
            assert cm.started
            assert not cm.finished
            assert cm.child_started
            assert not cm.child_finished

        assert cm.finished
        assert cm.child_finished
