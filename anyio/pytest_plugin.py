from functools import partial
from inspect import iscoroutinefunction

import pytest
from async_generator import isasyncgenfunction

from . import run, BACKENDS


def pytest_configure(config):
    config.addinivalue_line('markers', 'anyio: mark the (coroutine function) test to be run '
                                       'asynchronously via anyio.')


def pytest_addoption(parser):
    group = parser.getgroup('AnyIO')
    group.addoption(
        '--anyio-backends', action='store', dest='anyio_backends', default=BACKENDS[0],
        help='Comma separated list of backends to use for running asynchronous tests.',
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    def wrapper(*args, **kwargs):
        backend = kwargs['anyio_backend']
        if strip_backend:
            del kwargs['anyio_backend']

        if isasyncgenfunction(func):
            gen = func(*args, **kwargs)
            try:
                value = run(gen.__anext__, backend=backend)
            except StopAsyncIteration:
                raise RuntimeError('Async generator did not yield')

            yield value

            try:
                run(gen.__anext__, backend=backend)
            except StopAsyncIteration:
                pass
            else:
                run(gen.aclose, backend=backend)
                raise RuntimeError('Async generator fixture did not stop')
        else:
            yield run(partial(func, *args, **kwargs), backend=backend)

    func = fixturedef.func
    if (isasyncgenfunction(func) or iscoroutinefunction(func)) and 'anyio' in request.keywords:
        strip_backend = False
        if 'anyio_backend' not in fixturedef.argnames:
            fixturedef.argnames += ('anyio_backend',)
            strip_backend = True

        fixturedef.func = wrapper

    yield


def pytest_generate_tests(metafunc):
    marker = metafunc.definition.get_closest_marker('anyio')
    if marker:
        backends = metafunc.config.getoption('anyio_backends')
        if backends == 'all':
            backends = BACKENDS
        else:
            backends = backends.replace(' ', '').split(',')

        metafunc.fixturenames.append('anyio_backend')
        metafunc.parametrize('anyio_backend', backends, scope='session')


def check_test_function_type(func):
    if not iscoroutinefunction(func):
        funcname = '{}.{}'.format(func.__module__, func.__qualname__)
        pytest.fail('{} is not a coroutine function'.format(funcname))


@pytest.mark.tryfirst
def pytest_pyfunc_call(pyfuncitem):
    def run_with_hypothesis(**kwargs):
        run(partial(original_func, **kwargs), backend=backend)

    if pyfuncitem.get_closest_marker('anyio'):
        backend = pyfuncitem._request.getfixturevalue('anyio_backend')
        if hasattr(pyfuncitem.obj, 'hypothesis'):
            # Wrap the inner test function unless it's already wrapped
            original_func = pyfuncitem.obj.hypothesis.inner_test
            if original_func.__qualname__ != run_with_hypothesis.__qualname__:
                check_test_function_type(original_func)
                pyfuncitem.obj.hypothesis.inner_test = run_with_hypothesis

            return False

        check_test_function_type(pyfuncitem.obj)
        funcargs = pyfuncitem.funcargs
        testargs = {arg: funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames}
        run(partial(pyfuncitem.obj, **testargs), backend=backend)
        return True
