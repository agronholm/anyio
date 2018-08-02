import pytest


@pytest.fixture(params=['asyncio', 'curio', 'trio'], scope='session', autouse=True)
def hyperio_backend(request):
    return request.param
