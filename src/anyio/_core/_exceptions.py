from functools import partial
from inspect import getmro, isclass
from textwrap import indent
from traceback import format_exception
from typing import Callable, List, Optional, Sequence, Tuple, Type, Union, cast

ConditionParameter = Union[Type[BaseException], Tuple[Type[BaseException], ...],
                           Callable[[BaseException], bool]]


class BrokenResourceError(Exception):
    """
    Raised when trying to use a resource that has been rendered unusuable due to external causes
    (e.g. a send stream whose peer has disconnected).
    """


class BusyResourceError(Exception):
    """Raised when two tasks are trying to read from or write to the same resource concurrently."""

    def __init__(self, action: str):
        super().__init__(f'Another task is already {action} this resource')


class ClosedResourceError(Exception):
    """Raised when trying to use a resource that has been closed."""


class DelimiterNotFound(Exception):
    """
    Raised during :meth:`~anyio.streams.buffered.BufferedByteReceiveStream.receive_until` if the
    maximum number of bytes has been read without the delimiter being found.
    """

    def __init__(self, max_bytes: int) -> None:
        super().__init__(f'The delimiter was not found among the first {max_bytes} bytes')


class EndOfStream(Exception):
    """Raised when trying to read from a stream that has been closed from the other end."""


class ExceptionGroup(BaseException):
    """Raised when multiple exceptions have been raised in a task group."""

    SEPARATOR = '------------------------------------------------------------\n'

    #: the sequence of exceptions raised together
    exceptions: Sequence[BaseException]

    def __new__(cls, message: str, exceptions: List[BaseException]):
        return BaseException.__new__(cls)

    def __init__(self, message: str, exceptions: List[BaseException]):
        self.message = message
        self.exceptions = exceptions

    def __str__(self):
        tracebacks = self.SEPARATOR.join([
            f'{"".join(format_exception(type(exc), exc, exc.__traceback__))}'
            for exc in self.exceptions])
        tracebacks = indent(tracebacks, '  ')
        return f'ExceptionGroup: {self.message}\n  {self.SEPARATOR}{tracebacks}'

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self.message!r}, {self.exceptions!r})'

    @staticmethod
    def check_direct_subclass(exc: BaseException, parents: Tuple[Type[BaseException]]) -> bool:
        for cls in getmro(exc.__class__)[:-1]:
            if cls in parents:
                return True

        return False

    @staticmethod
    def _get_condition_filter(condition: ConditionParameter) -> Callable[[BaseException], bool]:
        if isclass(condition) and issubclass(cast(Type[BaseException], condition), BaseException):
            return partial(ExceptionGroup.check_direct_subclass, parents=(condition,))
        elif isinstance(condition, tuple):
            return partial(ExceptionGroup.check_direct_subclass, parents=condition)
        elif callable(condition):
            return cast(Callable[[BaseException], bool], condition)
        else:
            raise TypeError(f'Expected exception class, tuple of exception classes or a callable; '
                            f'got {condition.__class__.__name__} instead')

    def subgroup(self, condition: ConditionParameter) -> Optional['ExceptionGroup']:
        """
        Return an exception group containing only matching exceptions.

        Only the exceptions matching the condition are included. Nested exception groups are
        also filtered with this condition and empty groups are discarded. The actual exception
        group objects are not matched with the condition.

        See :pep:`654`  for more details.

        :param condition: one of the following:

            * a callable that takes an exception as the argument and returns ``True`` if
              the exception should be included
            * an exception class
            * a tuple of exception classes

        """
        condition = self._get_condition_filter(condition)
        exceptions: List[BaseException] = []
        modified = False
        for exc in self.exceptions:
            if isinstance(exc, ExceptionGroup):
                subgroup = exc.subgroup(condition)
                if subgroup is not None:
                    exceptions.append(subgroup)

                if subgroup is not exc:
                    modified = True
            elif condition(exc):
                exceptions.append(exc)
            else:
                modified = True

        if not modified:
            return self
        elif exceptions:
            group = self.__class__(self.message, exceptions)
            group.__cause__ = self.__cause__
            group.__context__ = self.__context__
            group.__traceback__ = self.__traceback__
            return group
        else:
            return None

    def split(self, condition: ConditionParameter) -> Tuple[Optional['ExceptionGroup'],
                                                            Optional['ExceptionGroup']]:
        """
        Split the exception group in two based on the given condition.

        This is like :meth:`subgroup` but a second group will be created which contains all the
        exceptions filtered out. If either group is empty, ``None`` will be returned in its place.

        See :pep:`654`  for more details.

        :param condition: one of the following:

            * a callable that takes an exception as the argument and returns ``True`` if
              the exception should be included
            * an exception class
            * a tuple of exception classes
        :return: a tuple of exception groups (or ``None`` where empty) where the first contains the
            matching exceptions and the second contains the ones that didn't match the condition

        """
        condition = self._get_condition_filter(condition)
        matching_exceptions: List[BaseException] = []
        nonmatching_exceptions: List[BaseException] = []
        for exc in self.exceptions:
            if isinstance(exc, ExceptionGroup):
                matching, nonmatching = exc.split(condition)
                if matching is not None:
                    matching_exceptions.append(matching)

                if nonmatching is not None:
                    nonmatching_exceptions.append(nonmatching)
            elif condition(exc):
                matching_exceptions.append(exc)
            else:
                nonmatching_exceptions.append(exc)

        matching_group: Optional[ExceptionGroup] = None
        if not nonmatching_exceptions:
            matching_group = self
        elif matching_exceptions:
            matching_group = self.__class__(self.message, matching_exceptions)
            matching_group.__cause__ = self.__cause__
            matching_group.__context__ = self.__context__
            matching_group.__traceback__ = self.__traceback__

        nonmatching_group: Optional[ExceptionGroup] = None
        if not matching_exceptions:
            nonmatching_group = self
        elif nonmatching_exceptions:
            nonmatching_group = ExceptionGroup(self.message, nonmatching_exceptions)
            nonmatching_group.__cause__ = self.__cause__
            nonmatching_group.__context__ = self.__context__
            nonmatching_group.__traceback__ = self.__traceback__

        return matching_group, nonmatching_group


class IncompleteRead(Exception):
    """
    Raised during :meth:`~anyio.streams.buffered.BufferedByteReceiveStream.receive_exactly` or
    :meth:`~anyio.streams.buffered.BufferedByteReceiveStream.receive_until` if the
    connection is closed before the requested amount of bytes has been read.
    """

    def __init__(self) -> None:
        super().__init__('The stream was closed before the read operation could be completed')


class TypedAttributeLookupError(LookupError):
    """
    Raised by :meth:`~anyio.TypedAttributeProvider.extra` when the given typed attribute is not
    found and no default value has been given.
    """


class WouldBlock(Exception):
    """Raised by ``X_nowait`` functions if ``X()`` would block."""
