import sys


def pytest_ignore_collect(path, config):
    return path.basename.endswith('_py36.py') and sys.version_info < (3, 6)
