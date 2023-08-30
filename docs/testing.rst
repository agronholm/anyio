Testing with AnyIO
==================

AnyIO provides built-in support for testing your library or application in the form of a
pytest_ plugin.

.. _pytest: https://docs.pytest.org/en/latest/

Creating asynchronous tests
---------------------------

Pytest does not natively support running asynchronous test functions, so they have to be
marked for the AnyIO pytest plugin to pick them up. This can be done in one of two ways:

#. Using the ``pytest.mark.anyio`` marker
#. Using the ``anyio_backend`` fixture, either directly or via another fixture

The simplest way is thus the following::

    import pytest

    # This is the same as using the @pytest.mark.anyio on all test functions in the module
    pytestmark = pytest.mark.anyio


    async def test_something():
        ...

Marking modules, classes or functions with this marker has the same effect as applying
the ``pytest.mark.usefixtures('anyio_backend')`` on them.

Thus, you can also require the fixture directly in your tests and fixtures::

    import pytest


    async def test_something(anyio_backend):
        ...

Specifying the backends to run on
---------------------------------

The ``anyio_backend`` fixture determines the backends and their options that tests and
fixtures are run with. The AnyIO pytest plugin comes with a function scoped fixture with
this name which runs everything on all supported backends.

If you change the backends/options for the entire project, then put something like this
in your top level ``conftest.py``::

    @pytest.fixture
    def anyio_backend():
        return 'asyncio'

If you want to specify different options for the selected backend, you can do so by
passing a tuple of (backend name, options dict)::

    @pytest.fixture(params=[
        pytest.param(('asyncio', {'use_uvloop': True}), id='asyncio+uvloop'),
        pytest.param(('asyncio', {'use_uvloop': False}), id='asyncio'),
        pytest.param(('trio', {'restrict_keyboard_interrupt_to_checkpoints': True}), id='trio')
    ])
    def anyio_backend(request):
        return request.param

If you need to run a single test on a specific backend, you can use
``@pytest.mark.parametrize`` (remember to add the ``anyio_backend`` parameter to the
actual test function, or pytest will complain)::

    @pytest.mark.parametrize('anyio_backend', ['asyncio'])
    async def test_on_asyncio_only(anyio_backend):
        ...

Because the ``anyio_backend`` fixture can return either a string or a tuple, there are
two additional function-scoped fixtures (which themselves depend on the
``anyio_backend`` fixture) provided for your convenience:

* ``anyio_backend_name``: the name of the backend (e.g. ``asyncio``)
* ``anyio_backend_options``: the dictionary of option keywords used to run the backend

Asynchronous fixtures
---------------------

The plugin also supports coroutine functions as fixtures, for the purpose of setting up
and tearing down asynchronous services used for tests.

There are two ways to get the AnyIO pytest plugin to run your asynchronous fixtures:

#. Use them in AnyIO enabled tests (see the first section)
#. Use the ``anyio_backend`` fixture (or any other fixture using it) in the fixture
   itself

The simplest way is using the first option::

    import pytest

    pytestmark = pytest.mark.anyio


    @pytest.fixture
    async def server():
        server = await setup_server()
        yield server
        await server.shutdown()


    async def test_server(server):
        result = await server.do_something()
        assert result == 'foo'


For ``autouse=True`` fixtures, you may need to use the other approach::

    @pytest.fixture(autouse=True)
    async def server(anyio_backend):
        server = await setup_server()
        yield
        await server.shutdown()


    async def test_server():
        result = await client.do_something_on_the_server()
        assert result == 'foo'


Using async fixtures with higher scopes
---------------------------------------

For async fixtures with scopes other than ``function``, you will need to define your own
``anyio_backend`` fixture because the default ``anyio_backend`` fixture is function
scoped::

    @pytest.fixture(scope='module')
    def anyio_backend():
        return 'asyncio'


    @pytest.fixture(scope='module')
    async def server(anyio_backend):
        server = await setup_server()
        yield
        await server.shutdown()

Technical details
-----------------

The fixtures and tests are run by a "test runner", implemented separately for each
backend. The test runner keeps an event loop open during the request, making it possible
for code in fixtures to communicate with the code in the tests (and each other).

The test runner is created when the first matching async test or fixture is about to be
run, and shut down when that same fixture is being torn down or the test has finished
running. As such, if no higher-order (scoped ``class`` or higher) async fixtures are
used, a separate test runner is created for each matching test. Conversely, if even one
async fixture, scoped higher than ``function``, is shared across all tests, only one
test runner will be created during the test session.

Context variable propagation
++++++++++++++++++++++++++++

The asynchronous test runner runs all async fixtures and tests in the same task, so
context variables set in async fixtures or tests, within an async test runner, will
affect other async fixtures and tests within the same runner. However, these context
variables are **not** carried over to synchronous tests and fixtures, or to other async
test runners.

Comparison with other async test runners
++++++++++++++++++++++++++++++++++++++++

The ``pytest-asyncio`` library only works with asyncio code. Like the AnyIO pytest
plugin, it can be made to support higher order fixtures (by specifying a higher order
``event_loop`` fixture). However, it runs the setup and teardown phases of each async
fixture in a new async task per operation, making context variable propagation
impossible and preventing task groups and cancel scopes from functioning properly.

The ``pytest-trio`` library, made for testing Trio projects, works only with Trio code.
Additionally, it only supports function scoped async fixtures. Another significant
difference with the AnyIO pytest plugin is that attempts to run the setup and teardown
for async fixtures concurrently when their dependency graphs allow that.
