from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import anyio.abc


def test_sourceless_install(tmp_path: Path) -> None:
    """
    Test how importing the anyio and anyio.abc packages works in a sourceless (.py files
    compiled to .pyc and then removed) installation.
    """

    # Create a new virtualenv
    subprocess.run([sys.executable, "-m", "venv", tmp_path], check=True)
    sys_exec_path = Path(sys.executable)
    bin_dir_name = sys_exec_path.parent.name
    interpreter_path = tmp_path / bin_dir_name / sys_exec_path.name
    assert interpreter_path.is_file()

    # Install this project into the virtualenv
    project_root = Path(__file__).parent.parent
    assert project_root.joinpath("src").is_dir()
    subprocess.run([interpreter_path, "-m", "pip", "install", project_root])

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
    subprocess.run([interpreter_path, "-m", "compileall", "-b", anyio_package_path])
    for root, _dirs, files in os.walk(anyio_package_path):
        for file in files:
            path = Path(root) / file
            if path.suffix == ".py":
                path.unlink(missing_ok=True)

    # Collect the module names of sample functions and classes and make sure they have
    # been changed to the containing module (anyio or anyio.abc)
    script_path = Path(__file__).parent / "samplescript.py"
    assert script_path.is_file()
    process = subprocess.run(
        [interpreter_path, script_path], capture_output=True, check=True
    )
    result = json.loads(process.stdout.decode("utf-8"))
    assert result["anyio.sleep"] == "anyio"
    assert result["anyio.CancelScope"] == "anyio"
    assert result["anyio.abc.CancelScope"] == "anyio"
    assert result["anyio.abc.UDPSocket"] == "anyio.abc"


def test_package_names() -> None:
    assert anyio.sleep.__module__ == "anyio"
    assert anyio.CancelScope.__module__ == "anyio"
    assert anyio.abc.CancelScope.__module__ == "anyio"
    assert anyio.abc.UDPSocket.__module__ == "anyio.abc"
