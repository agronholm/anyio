import multiprocessing
import os

import pytest

import anyio
from anyio._core._workers import WORKER_CACHE, WorkerProc

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def empty_proc_cache():
    while True:
        try:
            proc = WORKER_CACHE.pop()
            proc.kill()
            proc._proc.join()
        except IndexError:
            return


def _echo_and_pid(x):  # pragma: no cover
    return (x, os.getpid())


def _raise_pid():  # pragma: no cover
    raise ValueError(os.getpid())


async def test_run_in_worker():
    trio_pid = os.getpid()
    limiter = anyio.create_capacity_limiter(1)

    x, child_pid = await anyio.run_sync_in_worker_process(_echo_and_pid, 1, limiter=limiter)
    assert x == 1
    assert child_pid != trio_pid

    with pytest.raises(ValueError) as excinfo:
        await anyio.run_sync_in_worker_process(_raise_pid, limiter=limiter)
    print(excinfo.value.args)
    assert excinfo.value.args[0] != trio_pid


def _block_proc_on_queue(q, ev, done_ev):  # pragma: no cover
    # Make the process block for a controlled amount of time
    ev.set()
    q.get()
    done_ev.set()


async def test_cancellation(capfd):
    async def child(q, ev, done_ev, cancellable):
        print("start")
        try:
            return await anyio.run_sync_in_worker_process(
                _block_proc_on_queue, q, ev, done_ev, cancellable=cancellable
            )
        finally:
            print("exit")

    m = multiprocessing.Manager()
    q = m.Queue()
    ev = m.Event()
    done_ev = m.Event()

    # This one can't be cancelled
    async with anyio.create_task_group() as nursery:
        nursery.spawn(child, q, ev, done_ev, False)
        await anyio.run_sync_in_worker_thread(ev.wait, cancellable=True)
        nursery.cancel_scope.cancel()
        with anyio.open_cancel_scope(shield=True):
            await anyio.wait_all_tasks_blocked()
        # It's still running
        assert not done_ev.is_set()
        q.put(None)
        # Now it exits

    ev = m.Event()
    done_ev = m.Event()
    # But if we cancel *before* it enters, the entry is itself a cancellation
    # point
    with anyio.open_cancel_scope() as scope:
        scope.cancel()
        await child(q, ev, done_ev, False)
        assert False, 'unreachable'
    capfd.readouterr()

    ev = m.Event()
    done_ev = m.Event()
    # This is truly cancellable by killing the process
    async with anyio.create_task_group() as nursery:
        nursery.spawn(child, q, ev, done_ev, True)
        # Give it a chance to get started. (This is important because
        # to_thread_run_sync does a checkpoint_if_cancelled before
        # blocking on the thread, and we don't want to trigger this.)
        await anyio.wait_all_tasks_blocked()
        assert capfd.readouterr().out.rstrip() == "start"
        await anyio.run_sync_in_worker_thread(ev.wait, cancellable=True)
        # Then cancel it.
        nursery.cancel_scope.cancel()
    # The task exited, but the process died
    assert not done_ev.is_set()
    assert capfd.readouterr().out.rstrip() == "exit"


async def _null_async_fn():  # pragma: no cover
    pass


async def test_raises_on_async_fn():
    with pytest.raises(TypeError, match="expected a sync function"):
        await anyio.run_sync_in_worker_process(_null_async_fn)


async def test_prune_cache():
    # take proc's number and kill it for the next test
    while True:
        _, pid1 = await anyio.run_sync_in_worker_process(_echo_and_pid, None)
        try:
            proc = WORKER_CACHE.pop()
        except IndexError:  # pragma: no cover
            # In CI apparently the worker occasionally doesn't make it all the way
            # to the barrier in time. This is only a slight inefficiency rather
            # than a bug so for now just work around it with this loop.
            continue
        else:
            break
    proc.kill()
    with anyio.fail_after(1):
        await proc.wait()
    # put dead proc into the cache (normal code never does this)
    WORKER_CACHE.push(proc)
    # dead procs shouldn't pop out
    with pytest.raises(IndexError):
        WORKER_CACHE.pop()
    WORKER_CACHE.push(proc)
    # should spawn a new worker and remove the dead one
    _, pid2 = await anyio.run_sync_in_worker_process(_echo_and_pid, None)
    assert len(WORKER_CACHE) == 1
    assert pid1 != pid2


async def test_large_job():
    n = 2 ** 20
    x, _ = await anyio.run_sync_in_worker_process(_echo_and_pid, bytearray(n))
    assert len(x) == n


@pytest.fixture
async def proc():
    proc = WorkerProc()
    await anyio.run_sync_in_worker_thread(proc.wake_up)
    yield proc
    with anyio.fail_after(1):
        await proc.wait()


def _never_halts(ev):  # pragma: no cover
    # important difference from blocking call is cpu usage
    ev.set()
    while True:
        pass


async def test_run_sync_cancel_infinite_loop(proc):
    m = multiprocessing.Manager()
    ev = m.Event()

    async with anyio.create_task_group() as nursery:
        nursery.spawn(proc.run_sync, _never_halts, ev)
        await anyio.run_sync_in_worker_thread(ev.wait, cancellable=True)
        nursery.cancel_scope.cancel()


async def test_run_sync_raises_on_kill(proc):
    m = multiprocessing.Manager()
    ev = m.Event()

    with pytest.raises(anyio.BrokenWorkerError):
        with anyio.move_on_after(10):
            async with anyio.create_task_group() as nursery:
                nursery.spawn(proc.run_sync, _never_halts, ev)
                try:
                    await anyio.run_sync_in_worker_thread(ev.wait, cancellable=True)
                finally:
                    # if something goes wrong, free the thread
                    ev.set()
                proc.kill()  # also tests multiple calls to proc.kill


def _segfault_out_of_bounds_pointer():  # pragma: no cover
    # https://wiki.python.org/moin/CrashingPython
    import ctypes

    i = ctypes.c_char(b"a")
    j = ctypes.pointer(i)
    c = 0
    while True:
        j[c] = b"a"
        c += 1


async def test_run_sync_raises_on_segfault(proc):
    # This test was flaky on CI across several platforms and implementations.
    # I can reproduce it locally if there is some other process using the rest
    # of the CPU (F@H in this case) although I cannot explain why running this
    # on a busy machine would change the number of iterations (40-50k) needed
    # for the OS to notice there is something funny going on with memory access.
    # The usual symptom was for the segfault to occur, but the process
    # to fail to raise the error for more than one minute, which would
    # stall the test runner for 10 minutes.
    # Here we raise our own failure error before the test runner timeout (55s)
    # but xfail if we actually have to timeout.
    try:
        with anyio.fail_after(55):
            await proc.run_sync(_segfault_out_of_bounds_pointer)
    except anyio.BrokenWorkerError:
        pass
    except TimeoutError:  # pragma: no cover
        pytest.skip("Unable to cause segfault after 55 seconds.")
    else:  # pragma: no cover
        pytest.fail("No error was raised on segfault.")


async def test_exhaustively_cancel_run_sync(proc):
    # to test that cancellation does not ever leave a living process behind
    # currently requires manually targeting all but last checkpoints
    m = multiprocessing.Manager()
    ev = m.Event()

    # cancel at job send
    with anyio.fail_after(1):
        with anyio.move_on_after(0):
            await proc.run_sync(_never_halts, ev)
        await proc.wait()

    # cancel at result recv is tested elsewhere
