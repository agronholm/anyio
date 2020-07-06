import pytest
from hypothesis import given
from hypothesis.strategies import just

pytestmark = pytest.mark.anyio


@given(x=just(1))
async def test_hypothesis_wrapper(x):
    assert isinstance(x, int)


@given(x=just(1))
def test_hypothesis_wrapper_regular(x):
    assert isinstance(x, int)
