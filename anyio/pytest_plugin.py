from functools import partial
from inspect import iscoroutinefunction

import pytest
from async_generator import isasyncgenfunction

import anyio


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    def wrapper(*args, **kwargs):
        backend = kwargs['anyio_backend']
        if strip_backend:
            del kwargs['anyio_backend']

        if isasyncgenfunction(func):
            gen = func(*args, **kwargs)
            try:
                value = anyio.run(gen.__anext__, backend=backend)
            except StopAsyncIteration:
                raise RuntimeError('Async generator did not yield')

            yield value

            try:
                anyio.run(gen.__anext__, backend=backend)
            except StopAsyncIteration:
                pass
            else:
                anyio.run(gen.aclose)
                raise RuntimeError('Async generator fixture did not stop')
        else:
            yield anyio.run(partial(func, *args, **kwargs), backend=backend)

    func = fixturedef.func
    if isasyncgenfunction(func) or iscoroutinefunction(func):
        strip_backend = False
        if 'anyio_backend' not in fixturedef.argnames:
            fixturedef.argnames += ('anyio_backend',)
            strip_backend = True

        fixturedef.func = wrapper

    yield


def pytest_generate_tests(metafunc):
    marker = metafunc.definition.get_closest_marker('anyio')
    if marker:
        backends = marker.kwargs.get('backends', ['asyncio', 'curio', 'trio'])
        metafunc.fixturenames.append('anyio_backend')
        metafunc.parametrize('anyio_backend', backends, scope='session')


@pytest.mark.tryfirst
def pytest_pyfunc_call(pyfuncitem):
    if pyfuncitem.get_closest_marker('anyio'):
        funcargs = pyfuncitem.funcargs
        backend = pyfuncitem._request.getfixturevalue('anyio_backend')
        testargs = {arg: funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames}
        anyio.run(partial(pyfuncitem.obj, **testargs), backend=backend)
        return True
