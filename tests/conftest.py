import asyncio
import ssl

import pytest
import trustme

uvloop_marks = []
uvloop_policy = None
try:
    import uvloop
except ImportError:
    uvloop_marks.append(pytest.mark.skip(reason='uvloop not available'))
else:
    if (hasattr(asyncio.AbstractEventLoop, 'shutdown_default_executor')
            and not hasattr(uvloop.loop.Loop, 'shutdown_default_executor')):
        uvloop_marks.append(
            pytest.mark.skip(reason='uvloop is missing shutdown_default_executor()'))
    else:
        uvloop_policy = uvloop.EventLoopPolicy()

pytest_plugins = ['pytester']


@pytest.fixture(params=[
    pytest.param(('asyncio', {'debug': True, 'policy': asyncio.DefaultEventLoopPolicy()}),
                 id='asyncio'),
    pytest.param(('asyncio', {'debug': True, 'policy': uvloop_policy}), marks=uvloop_marks,
                 id='asyncio+uvloop'),
    pytest.param('curio'),
    pytest.param('trio')
])
def anyio_backend(request):
    return request.param


@pytest.fixture(scope='session')
def ca():
    return trustme.CA()


@pytest.fixture(scope='session')
def server_context(ca):
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert('localhost').configure_cert(server_context)
    return server_context


@pytest.fixture(scope='session')
def client_context(ca):
    client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ca.configure_trust(client_context)
    return client_context
