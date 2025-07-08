from __future__ import annotations

import pytest

import anyio


def test_broken_worker_interpreter_deprecation() -> None:
    with pytest.warns(DeprecationWarning):
        DeprecatedClass = anyio.BrokenWorkerIntepreter
    assert DeprecatedClass is anyio.BrokenWorkerInterpreter
