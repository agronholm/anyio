from functools import wraps


class DummyAwaitable:
    def __await__(self):
        if False:
            yield


dummy_awaitable = DummyAwaitable()


def wrap_as_awaitable(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        func(*args, **kwargs)
        return dummy_awaitable

    return wrapper
