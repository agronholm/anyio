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
