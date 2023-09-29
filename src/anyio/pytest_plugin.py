from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import Context, copy_context
from inspect import isasyncgenfunction, iscoroutinefunction
from typing import Any, Dict, Tuple, cast

import pytest
import sniffio
from _pytest.stash import StashKey

from ._core._eventloop import get_all_backends, get_async_backend
from ._run_in_context import ContextLike, context_wrap, context_wrap_async
from .abc import TestRunner

_current_runner: TestRunner | None = None
contextvars_context_key = StashKey[Context]()
_test_context_like_key = StashKey[ContextLike]()


class _TestContext(ContextLike):
    """This class manages transmission of sniffio.current_async_library_cvar"""

    def __init__(self, context: Context):
        self._context = context

    def run(self, func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return self._context.run(
            self._set_context_and_run,
            sniffio.current_async_library_cvar.get(None),
            func,
            *args,
            **kwargs,
        )

    def _set_context_and_run(
        self, current_async_library: str | None, func: Any, /, *args: Any, **kwargs: Any
    ) -> Any:
        reset_sniffio = None
        if current_async_library is not None:
            reset_sniffio = sniffio.current_async_library_cvar.set(
                current_async_library
            )

        try:
            return func(*args, **kwargs)
        finally:
            if reset_sniffio is not None:
                sniffio.current_async_library_cvar.reset(reset_sniffio)


def extract_backend_and_options(backend: object) -> tuple[str, dict[str, Any]]:
    if isinstance(backend, str):
        return backend, {}
    elif isinstance(backend, tuple) and len(backend) == 2:
        if isinstance(backend[0], str) and isinstance(backend[1], dict):
            return cast(Tuple[str, Dict[str, Any]], backend)

    raise TypeError("anyio_backend must be either a string or tuple of (string, dict)")


@contextmanager
def get_runner(
    backend_name: str, backend_options: dict[str, Any]
) -> Iterator[TestRunner]:
    global _current_runner
    if _current_runner:
        yield _current_runner
        return

    asynclib = get_async_backend(backend_name)
    token = None
    if sniffio.current_async_library_cvar.get(None) is None:
        # Since we're in control of the event loop, we can cache the name of the async
        # library
        token = sniffio.current_async_library_cvar.set(backend_name)

    try:
        backend_options = backend_options or {}
        with asynclib.create_test_runner(backend_options) as runner:
            _current_runner = runner
            yield runner
    finally:
        _current_runner = None
        if token:
            sniffio.current_async_library_cvar.reset(token)


def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        "markers",
        "anyio: mark the (coroutine function) test to be run "
        "asynchronously via anyio.",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    context = copy_context()
    session.stash[contextvars_context_key] = context
    session.stash[_test_context_like_key] = _TestContext(context)


def pytest_fixture_setup(fixturedef: Any, request: Any) -> None:
    context_like: ContextLike = request.session.stash[_test_context_like_key]

    def wrapper(*args, anyio_backend, **kwargs):  # type: ignore[no-untyped-def]
        backend_name, backend_options = extract_backend_and_options(anyio_backend)
        if has_backend_arg:
            kwargs["anyio_backend"] = anyio_backend

        with get_runner(backend_name, backend_options) as runner:
            context_wrapped = context_wrap_async(context_like, func)
            if isasyncgenfunction(func):
                yield from runner.run_asyncgen_fixture(context_wrapped, kwargs)
            else:
                yield runner.run_fixture(context_wrapped, kwargs)

    # Only apply this to coroutine functions and async generator functions in requests
    # that involve the anyio_backend fixture
    func = fixturedef.func
    if isasyncgenfunction(func) or iscoroutinefunction(func):
        if "anyio_backend" in request.fixturenames:
            has_backend_arg = "anyio_backend" in fixturedef.argnames
            setattr(wrapper, "_runs_in_session_context", True)
            fixturedef.func = wrapper
            if not has_backend_arg:
                fixturedef.argnames += ("anyio_backend",)
    elif not getattr(func, "_runs_in_session_context", False):
        wrapper = context_wrap(context_like, func)
        setattr(wrapper, "_runs_in_session_context", True)
        fixturedef.func = wrapper


@pytest.hookimpl(tryfirst=True)
def pytest_pycollect_makeitem(collector: Any, name: Any, obj: Any) -> None:
    if collector.istestfunction(obj, name):
        inner_func = obj.hypothesis.inner_test if hasattr(obj, "hypothesis") else obj
        if iscoroutinefunction(inner_func):
            marker = collector.get_closest_marker("anyio")
            own_markers = getattr(obj, "pytestmark", ())
            if marker or any(marker.name == "anyio" for marker in own_markers):
                pytest.mark.usefixtures("anyio_backend")(obj)


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: Any) -> bool | None:
    context_like: ContextLike = pyfuncitem.session.stash[_test_context_like_key]

    def run_with_hypothesis(**kwargs: Any) -> None:
        with get_runner(backend_name, backend_options) as runner:
            context_wrapped = context_wrap_async(context_like, original_func)
            runner.run_test(context_wrapped, kwargs)

    backend = pyfuncitem.funcargs.get("anyio_backend")
    if backend:
        backend_name, backend_options = extract_backend_and_options(backend)

        if hasattr(pyfuncitem.obj, "hypothesis"):
            # Wrap the inner test function unless it's already wrapped
            original_func = pyfuncitem.obj.hypothesis.inner_test
            if original_func.__qualname__ != run_with_hypothesis.__qualname__:
                if iscoroutinefunction(original_func):
                    pyfuncitem.obj.hypothesis.inner_test = run_with_hypothesis

            return None

        if iscoroutinefunction(pyfuncitem.obj):
            funcargs = pyfuncitem.funcargs
            testargs = {arg: funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames}
            with get_runner(backend_name, backend_options) as runner:
                context_wrapped = context_wrap_async(context_like, pyfuncitem.obj)
                runner.run_test(context_wrapped, testargs)

            return True

    if not iscoroutinefunction(pyfuncitem.obj):
        pyfuncitem.obj = context_wrap(context_like, pyfuncitem.obj)

    return None


@pytest.fixture(scope="module", params=get_all_backends())
def anyio_backend(request: Any) -> Any:
    return request.param


@pytest.fixture
def anyio_backend_name(anyio_backend: Any) -> str:
    if isinstance(anyio_backend, str):
        return anyio_backend
    else:
        return anyio_backend[0]


@pytest.fixture
def anyio_backend_options(anyio_backend: Any) -> dict[str, Any]:
    if isinstance(anyio_backend, str):
        return {}
    else:
        return anyio_backend[1]
