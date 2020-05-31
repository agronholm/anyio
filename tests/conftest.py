import asyncio
import sys

import pytest

uvloop_marks = []
try:
    import uvloop
except ImportError:
    uvloop_marks.append(pytest.mark.skip(reason='uvloop not available'))
else:
    if (hasattr(asyncio.AbstractEventLoop, 'shutdown_default_executor')
            and not hasattr(uvloop.loop.Loop, 'shutdown_default_executor')):
        uvloop_marks.append(
            pytest.mark.skip(reason='uvloop is missing shutdown_default_executor()'))


def pytest_ignore_collect(path, config):
    return path.basename.endswith('_py36.py') and sys.version_info < (3, 6)


@pytest.fixture(params=[
    pytest.param(('asyncio', {'use_uvloop': False}), id='asyncio'),
    pytest.param(('asyncio', {'use_uvloop': True}), id='asyncio+uvloop', marks=uvloop_marks),
    pytest.param('curio'),
    pytest.param('trio', marks=[pytest.mark.skipif(sys.version_info < (3, 6),
                                                   reason='trio only supports py3.6+')])
], autouse=True)
def anyio_backend(request):
    return request.param
