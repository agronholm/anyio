import pytest

from anyio import get_all_backends

pytestmark = pytest.mark.filterwarnings(
    'ignore:The TerminalReporter.writer attribute is deprecated:pytest.PytestDeprecationWarning:')


def test_plugin(testdir):
    testdir.makeconftest(
        """
        import anyio
        import sniffio
        import pytest


        @pytest.fixture
        async def async_fixture():
            await anyio.sleep(0)
            return sniffio.current_async_library()
        """
    )

    testdir.makepyfile(
        """
        import pytest

        import sniffio
        from anyio import get_all_backends, sleep
        from hypothesis import strategies, given


        @pytest.mark.anyio
        async def test_marked_test():
            # Test that tests marked with @pytest.mark.anyio are run
            pass

        @pytest.mark.anyio
        async def test_async_fixture_from_marked_test(async_fixture):
            # Test that async functions can use async fixtures
            assert async_fixture in get_all_backends()

        @pytest.mark.parametrize('anyio_backend', ['curio'])
        async def test_explicit_backend(anyio_backend):
            # Test that when specifying the backend explicitly with parametrize, the correct
            # backend is really used
            assert anyio_backend == 'curio'
            assert sniffio.current_async_library() == 'curio'

        def test_async_fixture_from_sync_test(anyio_backend_name, async_fixture):
            # Test that regular functions can use async fixtures too
            assert async_fixture == anyio_backend_name

        @pytest.mark.parametrize('anyio_backend', ['asyncio'], scope='class')
        class TestClassFixtures:
            @pytest.fixture(scope='class')
            async def async_class_fixture(self, anyio_backend):
                await sleep(0)
                return anyio_backend

            def test_class_fixture_in_test_method(self, async_class_fixture, anyio_backend_name):
                assert anyio_backend_name == 'asyncio'
                assert async_class_fixture == 'asyncio'
        """
    )

    result = testdir.runpytest('-v', '-p', 'no:curio')
    result.assert_outcomes(passed=3 * len(get_all_backends()) + 2)


def test_autouse_async_fixture(testdir):
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

    result = testdir.runpytest('-v', '-p', 'no:curio')
    result.assert_outcomes(passed=len(get_all_backends()))


def test_hypothesis_module_mark(testdir):
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

    result = testdir.runpytest('-v')
    result.assert_outcomes(passed=len(get_all_backends()) + 1, xfailed=len(get_all_backends()))


def test_hypothesis_function_mark(testdir):
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

    result = testdir.runpytest('-v')
    result.assert_outcomes(passed=2 * len(get_all_backends()), xfailed=2 * len(get_all_backends()))
