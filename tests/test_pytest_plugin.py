from __future__ import annotations

import pytest
from _pytest.logging import LogCaptureFixture
from _pytest.pytester import Pytester

from anyio import get_all_backends

pytestmark = pytest.mark.filterwarnings(
    "ignore:The TerminalReporter.writer attribute is deprecated"
    ":pytest.PytestDeprecationWarning:"
)

pytest_args = "-v", "-p", "anyio", "-p", "no:asyncio", "-p", "no:trio"


def test_plugin(testdir: Pytester) -> None:
    testdir.makeconftest(
        """
        from contextvars import ContextVar
        import sniffio
        import pytest

        from anyio import sleep

        var = ContextVar("var")


        @pytest.fixture
        async def async_fixture():
            await sleep(0)
            return sniffio.current_async_library()


        @pytest.fixture
        async def context_variable():
            token = var.set("testvalue")
            yield var
            var.reset(token)


        @pytest.fixture
        async def some_feature():
            yield None
            await sleep(0)
        """
    )

    testdir.makepyfile(
        """
        import pytest
        import sniffio
        from hypothesis import strategies, given

        from anyio import get_all_backends, sleep


        @pytest.mark.anyio
        async def test_marked_test() -> None:
            # Test that tests marked with @pytest.mark.anyio are run
            pass

        @pytest.mark.anyio
        async def test_async_fixture_from_marked_test(async_fixture):
            # Test that async functions can use async fixtures
            assert async_fixture in get_all_backends()

        def test_async_fixture_from_sync_test(anyio_backend_name, async_fixture):
            # Test that regular functions can use async fixtures too
            assert async_fixture == anyio_backend_name

        @pytest.mark.anyio
        async def test_skip_inline(some_feature):
            # Test for github #214
            pytest.skip("Test that skipping works")

        @pytest.mark.anyio
        async def test_contextvar(context_variable):
            # Test that a contextvar set in an async fixture is visible to the test
            assert context_variable.get() == "testvalue"
        """
    )

    result = testdir.runpytest(*pytest_args)
    result.assert_outcomes(
        passed=4 * len(get_all_backends()), skipped=len(get_all_backends())
    )


def test_asyncio(testdir: Pytester, caplog: LogCaptureFixture) -> None:
    testdir.makeconftest(
        """
        import asyncio
        import pytest
        import threading


        @pytest.fixture(scope='class')
        def anyio_backend():
            return 'asyncio'

        @pytest.fixture
        async def setup_fail_fixture():
            def callback():
                raise RuntimeError('failing fixture setup')

            asyncio.get_running_loop().call_soon(callback)
            await asyncio.sleep(0)
            yield None

        @pytest.fixture
        async def teardown_fail_fixture():
            def callback():
                raise RuntimeError('failing fixture teardown')

            yield None
            asyncio.get_running_loop().call_soon(callback)
            await asyncio.sleep(0)

        @pytest.fixture
        def no_thread_leaks_fixture():
            # this has to be non-async fixture so that it wraps up
            # after the event loop gets closed
            threads_before = threading.enumerate()
            yield
            threads_after = threading.enumerate()
            leaked_threads = set(threads_after) - set(threads_before)
            assert not leaked_threads
        """
    )

    testdir.makepyfile(
        """
        import asyncio

        import pytest

        pytestmark = pytest.mark.anyio


        class TestClassFixtures:
            @pytest.fixture(scope='class')
            async def async_class_fixture(self, anyio_backend):
                await asyncio.sleep(0)
                return anyio_backend

            def test_class_fixture_in_test_method(
                self,
                async_class_fixture,
                anyio_backend_name
            ):
                assert anyio_backend_name == 'asyncio'
                assert async_class_fixture == 'asyncio'

        async def test_callback_exception_during_test() -> None:
            def callback():
                nonlocal started
                started = True
                raise Exception('foo')

            started = False
            asyncio.get_running_loop().call_soon(callback)
            await asyncio.sleep(0)
            assert started

        async def test_callback_exception_during_setup(setup_fail_fixture):
            pass

        async def test_callback_exception_during_teardown(teardown_fail_fixture):
            pass

        async def test_exception_handler_no_exception():
            asyncio.get_event_loop().call_exception_handler(
                {"message": "bogus error"}
            )
            await asyncio.sleep(0.1)

        async def test_shutdown_default_executor(no_thread_leaks_fixture):
            # Test for github #503
            asyncio.get_event_loop().run_in_executor(None, lambda: 1)
        """
    )

    result = testdir.runpytest(*pytest_args)
    result.assert_outcomes(passed=4, failed=1, errors=2)
    assert len(caplog.messages) == 1
    assert caplog.messages[0] == "bogus error"


def test_autouse_async_fixture(testdir: Pytester) -> None:
    testdir.makeconftest(
        """
        import pytest

        autouse_backend = None


        @pytest.fixture(autouse=True)
        async def autouse_async_fixture(anyio_backend_name):
            global autouse_backend
            autouse_backend = anyio_backend_name

        @pytest.fixture
        def autouse_backend_name():
            return autouse_backend
        """
    )

    testdir.makepyfile(
        """
        import pytest

        import sniffio
        from anyio import get_all_backends, sleep


        def test_autouse_backend(autouse_backend_name):
            # Test that async autouse fixtures are triggered
            assert autouse_backend_name in get_all_backends()
        """
    )

    result = testdir.runpytest_subprocess(*pytest_args)
    result.assert_outcomes(passed=len(get_all_backends()))


def test_cancel_scope_in_asyncgen_fixture(testdir: Pytester) -> None:
    testdir.makepyfile(
        """
        import pytest

        from anyio import create_task_group, sleep


        @pytest.fixture
        async def asyncgen_fixture():
            async with create_task_group() as tg:
                tg.cancel_scope.cancel()
                await sleep(1)

            yield 1


        @pytest.mark.anyio
        async def test_cancel_in_asyncgen_fixture(asyncgen_fixture):
            assert asyncgen_fixture == 1
        """
    )

    result = testdir.runpytest_subprocess(*pytest_args)
    result.assert_outcomes(passed=len(get_all_backends()))


def test_module_scoped_task_group_fixture(testdir: Pytester) -> None:
    testdir.makeconftest(
        """
        import pytest

        from anyio import (
            CancelScope,
            create_memory_object_stream,
            create_task_group,
            get_all_backends,
        )


        @pytest.fixture(scope="module", params=get_all_backends())
        def anyio_backend():
            return 'asyncio'


        @pytest.fixture(scope="module")
        async def task_group():
            async with create_task_group() as tg:
                yield tg


        @pytest.fixture
        async def streams(task_group):
            async def echo_messages(*, task_status):
                with CancelScope() as cancel_scope:
                    task_status.started(cancel_scope)
                    async for obj in receive1:
                        await send2.send(obj)

            send1, receive1 = create_memory_object_stream()
            send2, receive2 = create_memory_object_stream()
            cancel_scope = await task_group.start(echo_messages)
            yield send1, receive2
            cancel_scope.cancel()
        """
    )

    testdir.makepyfile(
        """
        import pytest


        @pytest.mark.anyio
        async def test_task_group(streams):
            send1, receive2 = streams
            await send1.send("hello")
            assert await receive2.receive() == "hello"
        """
    )

    result = testdir.runpytest_subprocess(*pytest_args)
    result.assert_outcomes(passed=len(get_all_backends()))


def test_async_fixture_teardown_after_sync_test(testdir: Pytester) -> None:
    # Regression test for #619
    testdir.makepyfile(
        """
        import pytest

        from anyio import create_task_group, sleep

        @pytest.fixture(scope="session")
        def anyio_backend():
            return "asyncio"


        @pytest.fixture(scope="module")
        async def bbbbbb():
            yield ""


        @pytest.fixture(scope="module")
        async def aaaaaa():
            yield ""


        @pytest.mark.anyio
        async def test_1(bbbbbb):
            pass


        @pytest.mark.anyio
        async def test_2(aaaaaa, bbbbbb):
            pass
        """
    )

    result = testdir.runpytest_subprocess(*pytest_args)
    result.assert_outcomes(passed=2)


def test_hypothesis_module_mark(testdir: Pytester) -> None:
    testdir.makepyfile(
        """
        import pytest
        from hypothesis import given
        from hypothesis.strategies import just

        pytestmark = pytest.mark.anyio


        @given(x=just(1))
        async def test_hypothesis_wrapper(x):
            assert isinstance(x, int)


        @given(x=just(1))
        def test_hypothesis_wrapper_regular(x):
            assert isinstance(x, int)


        @pytest.mark.xfail(strict=True)
        @given(x=just(1))
        async def test_hypothesis_wrapper_failing(x):
            pytest.fail('This test failed successfully')
        """
    )

    result = testdir.runpytest(*pytest_args)
    result.assert_outcomes(
        passed=len(get_all_backends()) + 1, xfailed=len(get_all_backends())
    )


def test_hypothesis_function_mark(testdir: Pytester) -> None:
    testdir.makepyfile(
        """
        import pytest
        from hypothesis import given
        from hypothesis.strategies import just


        @pytest.mark.anyio
        @given(x=just(1))
        async def test_anyio_mark_first(x):
            assert isinstance(x, int)


        @given(x=just(1))
        @pytest.mark.anyio
        async def test_anyio_mark_last(x):
            assert isinstance(x, int)


        @pytest.mark.xfail(strict=True)
        @pytest.mark.anyio
        @given(x=just(1))
        async def test_anyio_mark_first_fail(x):
            pytest.fail('This test failed successfully')


        @given(x=just(1))
        @pytest.mark.xfail(strict=True)
        @pytest.mark.anyio
        async def test_anyio_mark_last_fail(x):
            pytest.fail('This test failed successfully')
        """
    )

    result = testdir.runpytest(*pytest_args)
    result.assert_outcomes(
        passed=2 * len(get_all_backends()), xfailed=2 * len(get_all_backends())
    )
