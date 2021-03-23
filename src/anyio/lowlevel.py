from typing import Any, Dict, Generic, Set, TypeVar, Union, cast
from weakref import WeakKeyDictionary

from ._core._eventloop import get_asynclib

T = TypeVar('T')
D = TypeVar('D')


async def checkpoint() -> None:
    """
    Check for cancellation and allow the scheduler to switch to another task.

    Equivalent to (but more efficient than)::

        await checkpoint_if_cancelled()
        await cancel_shielded_checkpoint()

    .. versionadded:: 3.0

    """
    await get_asynclib().checkpoint()


async def checkpoint_if_cancelled():
    """
    Enter a checkpoint if the enclosing cancel scope has been cancelled.

    This does not allow the scheduler to switch to a different task.

    .. versionadded:: 3.0

    """
    await get_asynclib().checkpoint_if_cancelled()


async def cancel_shielded_checkpoint() -> None:
    """
    Allow the scheduler to switch to another task but without checking for cancellation.

    Equivalent to (but potentially more efficient than)::

        with CancelScope(shield=True):
            await checkpoint()

    .. versionadded:: 3.0

    """
    await get_asynclib().cancel_shielded_checkpoint()


def current_token() -> object:
    """Return a backend specific token object that can be used to get back to the event loop."""
    return get_asynclib().current_token()


_run_vars = WeakKeyDictionary()  # type: WeakKeyDictionary[Any, Dict[str, Any]]
_token_wrappers: Dict[Any, '_TokenWrapper'] = {}


class _TokenWrapper:
    __slots__ = '_token', '__weakref__'

    def __init__(self, token):
        self._token = token

    def __eq__(self, other):
        return self._token is other._token

    def __hash__(self):
        return hash(self._token)


class RunvarToken:
    __slots__ = '_var', '_value', '_redeemed'

    def __init__(self, var: 'RunVar', value):
        self._var = var
        self._value = value
        self._redeemed = False


class RunVar(Generic[T]):
    """Like a :class:`~contextvars.ContextVar`, expect scoped to the running event loop."""
    __slots__ = '_name', '_default'

    NO_VALUE_SET = object()

    _token_wrappers: Set[_TokenWrapper] = set()

    def __init__(self, name: str, default: Union[T, object] = NO_VALUE_SET):
        self._name = name
        self._default = default

    @property
    def _current_vars(self) -> Dict[str, T]:
        token = current_token()
        while True:
            try:
                return _run_vars[token]
            except TypeError:
                # Happens when token isn't weak referable (TrioToken).
                # This workaround does mean that some memory will leak on Trio until the problem
                # is fixed on their end.
                token = _TokenWrapper(token)
                self._token_wrappers.add(token)
            except KeyError:
                run_vars = _run_vars[token] = {}
                return run_vars

    def get(self, default: Union[T, object] = NO_VALUE_SET) -> T:
        try:
            return self._current_vars[self._name]
        except KeyError:
            if default is not RunVar.NO_VALUE_SET:
                return cast(T, default)
            elif self._default is not RunVar.NO_VALUE_SET:
                return cast(T, self._default)

        raise LookupError(f'Run variable "{self._name}" has no value and no default set')

    def set(self, value: T) -> RunvarToken:
        current_vars = self._current_vars
        token = RunvarToken(self, current_vars.get(self._name, RunVar.NO_VALUE_SET))
        current_vars[self._name] = value
        return token

    def reset(self, token: RunvarToken) -> None:
        if token._var is not self:
            raise ValueError('This token does not belong to this RunVar')

        if token._redeemed:
            raise ValueError('This token has already been used')

        if token._value is RunVar.NO_VALUE_SET:
            try:
                del self._current_vars[self._name]
            except KeyError:
                pass
        else:
            self._current_vars[self._name] = token._value

        token._redeemed = True

    def __repr__(self):
        return f'<RunVar name={self._name!r}>'
