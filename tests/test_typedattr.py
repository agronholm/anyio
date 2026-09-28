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


def test_typedattr_set_missing_annotation() -> None:
    """
    Test that a public attribute without a type annotation is rejected.

    """

    with pytest.raises(
        TypeError, match="^Attribute 'attr' is missing its type annotation$"
    ):

        class BadAttributeSet(TypedAttributeSet):
            attr = typed_attribute()


def test_typedattr_set_subclassing() -> None:
    """
    Test that an attribute set can be subclassed, and that the attributes inherited
    from the base set are not reported as missing annotations.

    """

    class BaseAttributeSet(TypedAttributeSet):
        attr1: int = typed_attribute()

    class DerivedAttributeSet(BaseAttributeSet):
        attr2: str = typed_attribute()

    assert DerivedAttributeSet.attr1 is BaseAttributeSet.attr1
    assert DerivedAttributeSet.attr2 is not None
    assert "attr2" in dir(DerivedAttributeSet)


def test_typedattr_set_empty_subclass() -> None:
    """
    Test that a subclass that adds no attributes of its own is accepted.

    """

    class BaseAttributeSet(TypedAttributeSet):
        attr1: int = typed_attribute()

    class DerivedAttributeSet(BaseAttributeSet):
        pass

    assert DerivedAttributeSet.attr1 is BaseAttributeSet.attr1


def test_typedattr_set_subclass_missing_annotation() -> None:
    """
    Test that the annotation check still applies to the attributes declared by the
    subclass itself.

    """

    class BaseAttributeSet(TypedAttributeSet):
        attr1: int = typed_attribute()

    with pytest.raises(
        TypeError, match="^Attribute 'attr2' is missing its type annotation$"
    ):

        class DerivedAttributeSet(BaseAttributeSet):
            attr2 = typed_attribute()
