Contributing to AnyIO
=====================

If you wish to contribute a fix or feature to AnyIO, please follow the following
guidelines.

When you make a pull request against the main AnyIO codebase, Github runs the AnyIO test
suite against your modified code. Before making a pull request, you should ensure that
the modified code passes tests locally. To that end, the use of tox_ is recommended. The
default tox run first runs ``pre-commit`` and then the actual test suite. To run the
checks on all environments in parallel, invoke tox with ``tox -p``.

To build the documentation, run ``tox -e docs`` which will generate a directory named
``build`` in which you may view the formatted HTML documentation.

AnyIO uses pre-commit_ to perform several code style/quality checks. It is recommended
to activate pre-commit_ on your local clone of the repository (using
``pre-commit install``) to ensure that your changes will pass the same checks on GitHub.

.. _tox: https://tox.wiki/en/latest/installation.html
.. _pre-commit: https://pre-commit.com/#installation

Making a pull request on Github
-------------------------------

To get your changes merged to the main codebase, you need a Github account.

#. Fork the repository (if you don't have your own fork of it yet) by navigating to the
   `main AnyIO repository`_ and clicking on "Fork" near the top right corner.
#. Clone the forked repository to your local machine with
   ``git clone git@github.com/yourusername/anyio``.
#. Create a branch for your pull request, like ``git checkout -b myfixname``
#. Make the desired changes to the code base.
#. Commit your changes locally. If your changes close an existing issue, add the text
   ``Fixes XXX.`` or ``Closes XXX.`` to the commit message (where XXX is the issue
   number).
#. Push the changeset(s) to your forked repository (``git push``)
#. Navigate to Pull requests page on the original repository (not your fork) and click
   "New pull request"
#. Click on the text "compare across forks".
#. Select your own fork as the head repository and then select the correct branch name.
#. Click on "Create pull request".

If you have trouble, consult the `pull request making guide`_ on opensource.com.

.. _main AnyIO repository: https://github.com/agronholm/anyio
.. _pull request making guide:
    https://opensource.com/article/19/7/create-pull-request-github

Making a release
----------------

Releases can only be made by the repository owner. While any collaborator with write
access can start the release workflows, every job that runs in the ``release``
environment waits until the owner approves it. This also keeps the credentials used for
pushing the release commit and publishing to PyPI out of reach until the approval.

The changelog is generated from the news fragments in ``changelog.d/`` with Towncrier_
as part of the release. The pending changes can be previewed in the ``UNRELEASED``
section of the version history in the latest documentation.

To make a release:

#. Start the release workflow with ``gh workflow run release.yml``, or via
   "Run workflow" on the "Release a new version" workflow on the Actions tab. Without
   an explicit version, the latest release is bumped based on the news fragments:

   * the major version, if there are backwards incompatible changes (``breaking``)
   * the minor version, if there are new features (``added``)
   * the patch version otherwise

   To release a specific version, such as a pre-release, pass it explicitly:
   ``gh workflow run release.yml -f version=4.16.0rc1``. Pre-releases keep the news
   fragments, so the final release lists all the changes since the previous one.
#. Approve the deployment to the ``release`` environment. The workflow then credits the
   pull request authors, generates the changelog, removes the news fragments, commits
   the result and tags it as the new version.
#. The pushed tag triggers the "Publish packages to PyPI" workflow. Approve its
   deployments to have the packages uploaded to PyPI and a GitHub release created with
   the release notes from the changelog.

Do not push version tags manually. The publishing workflow refuses to publish any
version that has no entry in the version history.

If a release fails due to a temporary problem:

* If the release workflow failed, run it again. It does nothing to the repository unless
  it succeeds, and refuses to run for a version that has already been tagged.
* If the publishing workflow failed, re-run its failed jobs with
  ``gh run rerun <run id> --failed``. If it was never triggered, or the run is too old
  to be re-run, start it for the existing tag with
  ``gh workflow run publish.yml --ref <version>``.

If something went wrong with the release itself, make a new release (for example
``4.16.0.post1``) rather than moving or deleting the tag.

.. _Towncrier: https://towncrier.readthedocs.io/
