from setuptools import setup

setup(
    use_scm_version={
        'version_scheme': 'post-release',
        'local_scheme': 'dirty-tag'
    },
    setup_requires=[
        'setuptools_scm >= 1.7.0'
    ]
)
