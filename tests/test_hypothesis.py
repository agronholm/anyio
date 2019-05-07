import pytest
from hypothesis import given
from hypothesis.strategies import just


@pytest.mark.anyio
@given(x=just(1))
async def test_hypothesis_wrapper(x):
    assert isinstance(x, int)
