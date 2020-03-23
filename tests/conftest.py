import sys

import pytest

try:
    import uvloop
except ImportError:
    uvloop = None


def pytest_ignore_collect(path, config):
    return path.basename.endswith('_py36.py') and sys.version_info < (3, 6)


@pytest.fixture(params=[
    pytest.param(('asyncio', {'use_uvloop': False}), id='asyncio'),
    pytest.param(('asyncio', {'use_uvloop': True}), id='asyncio+uvloop',
                 marks=[pytest.mark.skipif(uvloop is None, reason='uvloop not available')]),
    pytest.param('curio'),
    pytest.param('trio')
], autouse=True)
def anyio_backend(request):
    return request.param
