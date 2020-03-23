Testing with AnyIO
==================

AnyIO provides built-in support for testing your library or application in the form of a pytest_
plugin.

.. _pytest: https://docs.pytest.org/en/latest/

Creating asynchronous tests
---------------------------

To mark a coroutine function to be run via :func:`anyio.run`, simply add the ``@pytest.mark.anyio``
decorator::

    import pytest


    @pytest.mark.anyio
    async def test_something():
        pass

Asynchronous fixtures
---------------------

The plugin also supports coroutine functions as fixtures, for the purpose of setting up and tearing
down asynchronous services used for tests::

    import pytest


    @pytest.fixture
    async def server():
        server = await setup_server()
        yield server
        await server.shutdown()


    @pytest.mark.anyio
    async def test_server(server):
        result = await server.do_something()
        assert result == 'foo'

Any coroutine fixture that is activated by a test marked with ``@pytest.mark.anyio`` will be run
with the same backend as the test itself. Both plain coroutine functions and asynchronous generator
functions are supported in the same manner as pytest itself does with regular functions and
generator functions.

.. note:: If you need Python 3.5 compatibility, please use the async_generator_ library to replace
          the async generator syntax that was introduced in Python 3.6.

.. _async_generator: https://github.com/python-trio/async_generator

Specifying the backend to run on
--------------------------------

By default, all tests are run against the default backend (asyncio). The pytest plugin provides a
command line switch (``--anyio-backends``) for selecting which backend(s) to run your tests
against. By specifying a special value, ``all``, it will run against all available backends.

For example, to run your test suite against the curio and trio backends:

.. code-block:: bash

    pytest --anyio-backends=curio,trio

Behind the scenes, any function that uses the ``@pytest.mark.anyio`` marker gets parametrized by
the plugin to use the ``anyio_backend`` fixture. One alternative is to do this parametrization on
your own::

    @pytest.mark.parametrize('anyio_backend', ['asyncio'])
    async def test_on_asyncio_only(anyio_backend):
        ...

Or you can write a simple fixture by the same name that provides the back-end name::

    @pytest.fixture(params=['asyncio'])
    def anyio_backend(request):
        return request.param

If you want to specify different options for the selected backend, you can do so by passing a tuple
of (backend name, options dict). The latter is passed as keyword arguments to :func:`anyio.run`::

    @pytest.fixture(params=[
        pytest.param(('asyncio', {'use_uvloop': True}), id='asyncio+uvloop'),
        pytest.param(('asyncio', {'use_uvloop': False}), id='asyncio'),
        pytest.param('curio'),
        pytest.param(('trio', {'restrict_keyboard_interrupt_to_checkpoints': True}), id='trio')
    ])
    def anyio_backend(request):
        return request.param

Because the ``anyio_backend`` fixture can return either a string or a tuple, there are two
additional fixtures (which themselves depend on the ``anyio_backend`` fixture) provided for your
convenience:

* ``anyio_backend_name``: the name of the backend (e.g. ``asyncio``)
* ``anyio_backend_options``: the dictionary of option keywords used to run the backend

Using AnyIO from regular tests
------------------------------

In rare cases, you may need to have tests that run against whatever backends you have chosen to
work with. For this, you can add the ``anyio_backend`` parameter to your test. It will be filled
in with the name of each of the selected backends in turn::

    def test_something(anyio_backend):
        assert anyio_backend in ('asyncio', 'curio', 'trio')
