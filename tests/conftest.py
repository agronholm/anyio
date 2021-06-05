import asyncio
import ssl
from ssl import SSLContext
from typing import Any, Dict, Generator, Tuple

import pytest
import trustme
from _pytest.fixtures import SubRequest
from trustme import CA

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
    pytest.param('trio')
])
def anyio_backend(request: SubRequest) -> Tuple[str, Dict[str, Any]]:
    return request.param


@pytest.fixture(scope='session')
def ca() -> CA:
    return trustme.CA()


@pytest.fixture(scope='session')
def server_context(ca: CA) -> SSLContext:
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert('localhost').configure_cert(server_context)
    return server_context


@pytest.fixture(scope='session')
def client_context(ca: CA) -> SSLContext:
    client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ca.configure_trust(client_context)
    return client_context


@pytest.fixture
def asyncio_event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.DefaultEventLoopPolicy().new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    asyncio.set_event_loop(None)
    loop.close()
