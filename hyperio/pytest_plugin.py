import inspect
from functools import partial

import pytest
from async_generator import isasyncgenfunction

import hyperio


# @pytest.hookimpl(hookwrapper=True)
# def pytest_fixture_setup(fixturedef, request):
#     """Adjust the event loop policy when an event loop is produced."""
#     if isasyncgenfunction(fixturedef.func):
#         # This is an async generator function. Wrap it accordingly.
#         f = fixturedef.func
#
#         strip_event_loop = False
#         if 'event_loop' not in fixturedef.argnames:
#             fixturedef.argnames += ('event_loop', )
#             strip_event_loop = True
#         strip_request = False
#         if 'request' not in fixturedef.argnames:
#             fixturedef.argnames += ('request', )
#             strip_request = True
#
#         def wrapper(*args, **kwargs):
#             loop = kwargs['event_loop']
#             request = kwargs['request']
#             if strip_event_loop:
#                 del kwargs['event_loop']
#             if strip_request:
#                 del kwargs['request']
#
#             gen_obj = f(*args, **kwargs)
#
#             async def setup():
#                 res = await gen_obj.__anext__()
#                 return res
#
#             def finalizer():
#                 """Yield again, to finalize."""
#                 async def async_finalizer():
#                     try:
#                         await gen_obj.__anext__()
#                     except StopAsyncIteration:
#                         pass
#                     else:
#                         msg = "Async generator fixture didn't stop."
#                         msg += "Yield only once."
#                         raise ValueError(msg)
#
#                 loop.run_until_complete(async_finalizer())
#
#             request.addfinalizer(finalizer)
#
#             return loop.run_until_complete(setup())
#
#         fixturedef.func = wrapper
#     elif inspect.iscoroutinefunction(fixturedef.func):
#         # Just a coroutine, not an async generator.
#         f = fixturedef.func
#
#         strip_event_loop = False
#         if 'event_loop' not in fixturedef.argnames:
#             fixturedef.argnames += ('event_loop', )
#             strip_event_loop = True
#
#         def wrapper(*args, **kwargs):
#             loop = kwargs['event_loop']
#             if strip_event_loop:
#                 del kwargs['event_loop']
#
#             async def setup():
#                 res = await f(*args, **kwargs)
#                 return res
#
#             return loop.run_until_complete(setup())
#
#         fixturedef.func = wrapper
#
#     outcome = yield
#
#     if fixturedef.argname == "event_loop" and 'hyperio' in request.keywords:
#         loop = outcome.get_result()
#         for kw in _markers_2_fixtures.keys():
#             if kw not in request.keywords:
#                 continue
#             policy = asyncio.get_event_loop_policy()
#             try:
#                 old_loop = policy.get_event_loop()
#             except RuntimeError as exc:
#                 if 'no current event loop' not in str(exc):
#                     raise
#                 old_loop = None
#             policy.set_event_loop(loop)
#             fixturedef.addfinalizer(lambda: policy.set_event_loop(old_loop))


@pytest.mark.tryfirst
def pytest_pyfunc_call(pyfuncitem):
    if pyfuncitem.get_marker('hyperio'):
        funcargs = pyfuncitem.funcargs
        backend = funcargs.get('hyperio_backend', 'asyncio')
        testargs = {arg: funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames}
        hyperio.run(partial(pyfuncitem.obj, **testargs), backend=backend)
        return True
