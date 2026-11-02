from anyio import TypedAttributeSet, typed_attribute


class MyTypedAttribute(TypedAttributeSet):
    string_valued_attribute: str = typed_attribute()
    some_float_attribute: float = typed_attribute()
