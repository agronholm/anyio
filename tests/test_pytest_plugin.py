import pytest
from _pytest.pytester import Testdir

from anyio import get_all_backends

pytestmark = pytest.mark.filterwarnings(
    'ignore:The TerminalReporter.writer attribute is deprecated:pytest.PytestDeprecationWarning:')


def test_plugin(testdir: Testdir) -> None:
    testdir.makeconftest(
        """
        import sniffio
        import pytest

        from anyio import sleep


        @pytest.fixture
        async def async_fixture():
            await sleep(0)
            return sniffio.current_async_library()


        @pytest.fixture
        async def some_feature():
            yield None
            await sleep(0)
        """
    )

    testdir.makepyfile(
        """
        import asyncio

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
        """
    )

    result = testdir.runpytest('-v', '-p', 'no:asyncio')
    result.assert_outcomes(passed=3 * len(get_all_backends()), skipped=len(get_all_backends()))


def test_asyncio(testdir: Testdir) -> None:
    testdir.makeconftest(
        """
        import asyncio
        import pytest


        @pytest.fixture(scope='class')
        def anyio_backend():
            return 'asyncio'

        @pytest.fixture
        async def setup_fail_fixture():
            def callback():
                raise RuntimeError('failing fixture setup')

            asyncio.get_event_loop().call_soon(callback)
            await asyncio.sleep(0)
            yield None

        @pytest.fixture
        async def teardown_fail_fixture():
            def callback():
                raise RuntimeError('failing fixture teardown')

            yield None
            asyncio.get_event_loop().call_soon(callback)
            await asyncio.sleep(0)
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

            def test_class_fixture_in_test_method(self, async_class_fixture, anyio_backend_name):
                assert anyio_backend_name == 'asyncio'
                assert async_class_fixture == 'asyncio'

        async def test_callback_exception_during_test() -> None:
            def callback():
                nonlocal started
                started = True
                raise Exception('foo')

            started = False
            asyncio.get_event_loop().call_soon(callback)
            await asyncio.sleep(0)
            assert started

        async def test_callback_exception_during_setup(setup_fail_fixture):
            pass

        async def test_callback_exception_during_teardown(teardown_fail_fixture):
            pass
        """
    )

    result = testdir.runpytest('-v', '-p', 'no:asyncio')
    result.assert_outcomes(passed=2, failed=1, errors=2)


def test_autouse_async_fixture(testdir: Testdir) -> None:
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

    result = testdir.runpytest('-v', '-p', 'no:asyncio')
    result.assert_outcomes(passed=len(get_all_backends()))


def test_cancel_scope_in_asyncgen_fixture(testdir: Testdir) -> None:
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

    result = testdir.runpytest('-v', '-p', 'no:asyncio')
    result.assert_outcomes(passed=len(get_all_backends()))


def test_hypothesis_module_mark(testdir: Testdir) -> None:
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

    result = testdir.runpytest('-v', '-p', 'no:asyncio')
    result.assert_outcomes(passed=len(get_all_backends()) + 1, xfailed=len(get_all_backends()))


def test_hypothesis_function_mark(testdir: Testdir) -> None:
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

    result = testdir.runpytest('-v', '-p', 'no:asyncio')
    result.assert_outcomes(passed=2 * len(get_all_backends()), xfailed=2 * len(get_all_backends()))
