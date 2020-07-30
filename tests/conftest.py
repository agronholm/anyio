import asyncio

import pytest

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


@pytest.fixture(params=[
    pytest.param(('asyncio', {'policy': asyncio.DefaultEventLoopPolicy()}), id='asyncio'),
    pytest.param(('asyncio', {'policy': uvloop_policy}), id='asyncio+uvloop', marks=uvloop_marks),
    pytest.param('curio'),
    pytest.param('trio')
], autouse=True)
def anyio_backend(request):
    return request.param
