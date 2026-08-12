from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

import anyio.abc

DEPRECATIONS = {
    "anyio.BrokenWorkerIntepreter": "anyio.BrokenWorkerInterpreter",
    "anyio.abc.CapacityLimiter": "anyio.CapacityLimiter",
    "anyio.abc.Condition": "anyio.Condition",
    "anyio.abc.Event": "anyio.Event",
    "anyio.abc.Lock": "anyio.Lock",
    "anyio.abc.Semaphore": "anyio.Semaphore",
}


@pytest.mark.timeout(60)
def test_sourceless_install(tmp_path: Path) -> None:
    """
    Test how importing the anyio and anyio.abc packages works in a sourceless (.py files
    compiled to .pyc and then removed) installation.
    """

    # Create a new virtualenv
    subprocess.run([sys.executable, "-m", "venv", tmp_path], check=True)
    if platform.system() == "Windows":
        interpreter_path = tmp_path / "scripts" / "python.exe"
    else:
        interpreter_path = tmp_path / "bin" / "python"

    assert interpreter_path.is_file()

    # Install this project into the virtualenv
    project_root = Path(__file__).parent.parent
    assert project_root.joinpath("src").is_dir()
    subprocess.run([interpreter_path, "-m", "pip", "install", project_root], check=True)

    # Find out the path to the site-packages directory
    process = subprocess.run(
        [
            interpreter_path,
            "-c",
            "import sysconfig; print(sysconfig.get_paths()['purelib'])",
        ],
        capture_output=True,
        check=True,
    )
    site_packages_path = Path(process.stdout.strip().decode("utf-8"))
    assert site_packages_path.is_dir()

    # Compile .py -> .pyc and then delete the original source file in the installed dir
    anyio_package_path = site_packages_path / "anyio"
    assert anyio_package_path.is_dir()
    subprocess.run(
        [interpreter_path, "-m", "compileall", "-b", anyio_package_path], check=True
    )
    for root, _dirs, files in os.walk(anyio_package_path):
        for file in files:
            path = Path(root) / file
            if path.suffix == ".py":
                path.unlink(missing_ok=True)

    script = dedent(f"""\
    import json
    import sys
    import warnings

    import anyio.abc

    deprecated_items = {list(DEPRECATIONS)!r}
    deprecations = dict.fromkeys(deprecated_items, None)
    result = {{
        "deprecations": deprecations,
        "modulenames": {{
            "anyio.sleep": anyio.sleep.__module__,
            "anyio.CancelScope": anyio.CancelScope.__module__,
            "anyio.abc.CancelScope": anyio.abc.CancelScope.__module__,
            "anyio.abc.UDPSocket": anyio.abc.UDPSocket.__module__,
        }},
    }}

    for item in deprecated_items:
        module, name = item.rsplit(".", 1)
        with warnings.catch_warnings(record=True) as records:
            getattr(sys.modules[module], name)

        if records:
            warning = records[0].message
            replacement = str(warning).split()[-2]
            deprecations[item] = replacement

    json.dump(result, sys.stdout)
    """)

    # Collect the module names of sample functions and classes and make sure they have
    # been changed to the containing module (anyio or anyio.abc)
    # script_path = Path(__file__).parent / "samplescript.py"
    # assert script_path.is_file()
    process = subprocess.run(
        [interpreter_path, "-c", script],
        input=json.dumps(DEPRECATIONS).encode(),
        capture_output=True,
        check=True,
    )
    result = json.loads(process.stdout.decode("utf-8"))
    assert result["modulenames"] == {
        "anyio.sleep": "anyio",
        "anyio.CancelScope": "anyio",
        "anyio.abc.CancelScope": "anyio",
        "anyio.abc.UDPSocket": "anyio.abc",
    }
    assert result["deprecations"] == DEPRECATIONS


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_package_names() -> None:
    assert anyio.sleep.__module__ == "anyio"
    assert anyio.CancelScope.__module__ == "anyio"
    assert anyio.abc.CancelScope.__module__ == "anyio"  # type: ignore[attr-defined]
    assert anyio.abc.UDPSocket.__module__ == "anyio.abc"


def test_dir() -> None:
    assert "Event" in dir(anyio)
    assert "AsyncBackend" in dir(anyio.abc)


def test_deprecations() -> None:
    for old_name, new_name in DEPRECATIONS.items():
        module_name, attrname = old_name.rsplit(".", 1)
        with pytest.warns(DeprecationWarning):
            old_obj = getattr(sys.modules[module_name], attrname)

        module_name, attrname = new_name.rsplit(".", 1)
        new_obj = getattr(sys.modules[module_name], attrname)
        assert new_obj is old_obj
