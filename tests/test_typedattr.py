from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest

from anyio import TypedAttributeProvider, TypedAttributeSet, typed_attribute


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


def test_typedattr_set_subclassing() -> None:
    """
    Test that an attribute set can be subclassed, and that the attributes inherited
    from the base set are not reported as missing annotations.
    """

    class BaseAttributeSet(TypedAttributeSet):
        attr1: int = typed_attribute()

    class DerivedAttributeSet(BaseAttributeSet):
        attr2: str = typed_attribute()
