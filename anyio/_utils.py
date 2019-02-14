class DummyAwaitable:
    def __await__(self):
        if False:
            yield


dummy_awaitable = DummyAwaitable()
