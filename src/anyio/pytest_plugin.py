from __future__ import annotations

import sys
from collections.abc import Generator, Iterator
from contextlib import ExitStack, contextmanager
from inspect import isasyncgenfunction, iscoroutinefunction
from typing import Any, cast

import pytest
import sniffio
from _pytest.outcomes import Exit

from ._core._eventloop import get_all_backends, get_async_backend
from ._core._exceptions import iterate_exceptions
from .abc import TestRunner

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

_current_runner: TestRunner | None = None
_runner_stack: ExitStack | None = None
_runner_leases = 0


def extract_backend_and_options(backend: object) -> tuple[str, dict[str, Any]]:
    if isinstance(backend, str):
        return backend, {}
    elif isinstance(backend, tuple) and len(backend) == 2:
        if isinstance(backend[0], str) and isinstance(backend[1], dict):
            return cast(tuple[str, dict[str, Any]], backend)

    raise TypeError("anyio_backend must be either a string or tuple of (string, dict)")


@contextmanager
def get_runner(
    backend_name: str, backend_options: dict[str, Any]
) -> Iterator[TestRunner]:
    global _current_runner, _runner_leases, _runner_stack
    if _current_runner is None:
        asynclib = get_async_backend(backend_name)
        _runner_stack = ExitStack()
        if sniffio.current_async_library_cvar.get(None) is None:
            # Since we're in control of the event loop, we can cache the name of the
            # async library
            token = sniffio.current_async_library_cvar.set(backend_name)
            _runner_stack.callback(sniffio.current_async_library_cvar.reset, token)

        backend_options = backend_options or {}
        _current_runner = _runner_stack.enter_context(
            asynclib.create_test_runner(backend_options)
        )

    _runner_leases += 1
    try:
        yield _current_runner
    finally:
        _runner_leases -= 1
        if not _runner_leases:
            assert _runner_stack is not None
            _runner_stack.close()
            _runner_stack = _current_runner = None


def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        "markers",
        "anyio: mark the (coroutine function) test to be run "
        "asynchronously via anyio.",
    )


def _getimfunc(func: Any) -> Any:
    try:
        return func.__func__
    except AttributeError:
        return func


def _resolve_fixture_function(fixturedef: Any, request: Any) -> Any:
    """
    Get the actual callable that can be called to obtain the fixture
    value.

    copied from _pytest.fixtures.resolve_fixture_function
    """
    fixturefunc = fixturedef.func
    # The fixture function needs to be bound to the actual
    # request.instance so that code working with "fixturedef" behaves
    # as expected.
    instance = request.instance
    if instance is not None:
        # Handle the case where fixture is defined not in a test class, but some other class
        # (for example a plugin class with a fixture), see #2270.
        if hasattr(fixturefunc, "__self__") and not isinstance(
            instance,
            fixturefunc.__self__.__class__,
        ):
            return fixturefunc
        fixturefunc = _getimfunc(fixturedef.func)
        if fixturefunc != fixturedef.func:
            fixturefunc = fixturefunc.__get__(instance)
    return fixturefunc


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(fixturedef: Any, request: Any) -> Generator[Any, None, None]:
    def wrapper(*args, anyio_backend, **kwargs):  # type: ignore[no-untyped-def]
        backend_name, backend_options = extract_backend_and_options(anyio_backend)
        if has_backend_arg:
            kwargs["anyio_backend"] = anyio_backend

        with get_runner(backend_name, backend_options) as runner:
            if isasyncgenfunction(func):
                yield from runner.run_asyncgen_fixture(func, kwargs)
            else:
                yield runner.run_fixture(func, kwargs)

    with ExitStack() as stack:
        # Only apply this to coroutine functions and async generator functions in requests
        # that involve the anyio_backend fixture
        func = _resolve_fixture_function(fixturedef, request)
        if isasyncgenfunction(func) or iscoroutinefunction(func):
            if "anyio_backend" in request.fixturenames:
                has_backend_arg = "anyio_backend" in fixturedef.argnames
                original_func = fixturedef.func
                fixturedef.func = wrapper
                stack.callback(setattr, fixturedef, "func", original_func)

                if not has_backend_arg:
                    original_argnames = fixturedef.argnames
                    fixturedef.argnames = original_argnames + ("anyio_backend",)
                    stack.callback(setattr, fixturedef, "argnames", original_argnames)

        return (yield)


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
    def run_with_hypothesis(**kwargs: Any) -> None:
        with get_runner(backend_name, backend_options) as runner:
            runner.run_test(original_func, kwargs)

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
                try:
                    runner.run_test(pyfuncitem.obj, testargs)
                except ExceptionGroup as excgrp:
                    for exc in iterate_exceptions(excgrp):
                        if isinstance(exc, (Exit, KeyboardInterrupt, SystemExit)):
                            raise exc from excgrp

                    raise

            return True

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
