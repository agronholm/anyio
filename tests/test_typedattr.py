from __future__ import annotations

from typing import Any, Callable, Mapping

import pytest

from anyio import TypedAttributeProvider


class DummyAttributeProvider(TypedAttributeProvider):
    def get_dummyattr(self) -> str:
        raise KeyError("foo")

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return {str: self.get_dummyattr}


def test_typedattr_keyerror() -> None:
    """
    Test that if the extra attribute getter raises KeyError, it won't be confused for a
    missing attribute.

    """
    with pytest.raises(KeyError, match="^'foo'$"):
        DummyAttributeProvider().extra(str)
