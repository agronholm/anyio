from functools import partial
from inspect import iscoroutinefunction

import pytest

import hyperio

try:
    from async_generator import isasyncgenfunction
except ImportError:
    from inspect import isasyncgenfunction


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    def wrapper(*args, **kwargs):
        backend = kwargs['hyperio_backend']
        if strip_backend:
            del kwargs['hyperio_backend']

        if isasyncgenfunction(func):
            gen = func(*args, **kwargs)
            try:
                value = hyperio.run(gen.__anext__, backend=backend)
            except StopAsyncIteration:
                raise RuntimeError('Async generator did not yield')

            yield value

            try:
                hyperio.run(gen.__anext__, backend=backend)
            except StopAsyncIteration:
                pass
            else:
                hyperio.run(gen.aclose)
                raise RuntimeError('Async generator fixture did not stop')
        else:
            yield hyperio.run(partial(func, *args, **kwargs), backend=backend)

    func = fixturedef.func
    if hasattr(func, '__wrapped__'):
        func = func.__wrapped__

    if isasyncgenfunction(func) or iscoroutinefunction(func):
        strip_backend = False
        if 'hyperio_backend' not in fixturedef.argnames:
            fixturedef.argnames += ('hyperio_backend',)
            strip_backend = True

        fixturedef.func = wrapper

    yield


def pytest_generate_tests(metafunc):
    marker = metafunc.definition.get_closest_marker('hyperio')
    if marker:
        backends = marker.kwargs.get('backends', ['asyncio', 'curio', 'trio'])
        metafunc.fixturenames.append('hyperio_backend')
        metafunc.parametrize('hyperio_backend', backends, scope='session')


@pytest.mark.tryfirst
def pytest_pyfunc_call(pyfuncitem):
    if pyfuncitem.get_closest_marker('hyperio'):
        funcargs = pyfuncitem.funcargs
        backend = funcargs.get('hyperio_backend', 'asyncio')
        testargs = {arg: funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames}
        hyperio.run(partial(pyfuncitem.obj, **testargs), backend=backend)
        return True
