# AGENTS.md — Guidelines for AI Agents working on anyio

## Project Overview

AnyIO is a high-level asynchronous concurrency and networking library for Python that works on top of both **asyncio** and **Trio**. Source code lives in `src/`, tests in `tests/`.

## Building & Testing

- **Python**: Check the minimum Python version by looking at the `requires-python` field in `pyproject.toml`.
- **Install the project and test dependencies**: `pip install --group test -e .`.
- **Run tests**: `pytest` (runs from the `tests/` directory automatically via `pyproject.toml` config). Tests run against all supported backends by default.
- **Linting**: The project uses **pre-commit** for linting, formatting and static type checking. Run `pre-commit run -a` to check everything.

## Code Style

- Follow the existing code style — the project enforces it via Ruff (see `[tool.ruff]` in `pyproject.toml`).
- Import order is managed by Ruff's isort integration; always add `from __future__ import annotations` as the first import.
- Use the latest idioms supported by the minimum Python version (such as `X | Y` union syntax in annotations, etc.).
- Always add a blank line after a control block ends, and there is more code to follow. Do not add blank lines between related parts of the same control block (e.g. `if...elif...else`).

## Pull Request Guidelines

Important: Before making a pull request, check if anyone else has already made a PR that fixes the same issue or implements the same feature.
If there is an existing PR that does what your PR would do, and your PR would not be substantially superior, then do not send it.
Instead, collaborate with the original PR author to improve that one. Duplicate AI-generated PRs are grounds for a ban.

Every pull request **must** follow the PR template in `.github/pull_request_template.md`. Do **not** erase or replace the template contents — PRs that do so will be closed without review.

A properly filled-out PR contains:

### 1. Changes section

- Reference the related issue number, if applicable (e.g., `Fixes #123.`).
- Provide a short description of what the PR changes and why. This should be a terse, information-dense summary of what problem was fixed or what feature was added, or otherwise what was changed.

### 2. Checklist

Complete the checklist where applicable:
- **Tests** — Add or update tests in `tests/` that would fail without the patch.
- **Documentation** — Update docs in `docs/` if behavior changes or new features are introduced.
- **Changelog** — Add a new entry in `docs/versionhistory.rst`.

Trivial changes (typo fixes, code reformatting) may skip the checklist items.

### 3. Changelog entry format

A changelog entry should look like:

```md
- Fix big bad boo-boo in task groups
  (`#123 <https://github.com/agronholm/anyio/issues/123>`_; PR by @yourgithubaccount)
```

If there is no linked issue, link to the pull request itself instead (update the changelog after the PR is created to get the PR number).

### 4. Changelog entry placement

If the PR warrants a changelog entry, it must be added under the `**UNRELEASED**` section.
If there is no such section yet, add it to the top, right below the note about semantic versioning.
Entries in the changelog should be ordered as follows:

#. Backwards incompatible changes (prefixed with `**BACKWARDS INCOMPATIBLE**`)
#. New features (should start with the word `Added`)
#. Backwards compatible uncategorized but user-visible code changes (should start with the word `Changed`; add the entry below any new features but before bug fixes)
#. Bug fixes (should start with the word `Fixed`; add the entry to the bottom of the section)

### 5. Good and bad examples

Here is a good example of a PR that adds a new feature: https://github.com/agronholm/anyio/pull/1100
Here is a bad example of a PR that overwrites the PR template and lacks tests and a changelog entry: https://github.com/agronholm/anyio/pull/1112

## Repository Layout

| Path                               | Description                        |
|------------------------------------|------------------------------------|
| `src/anyio/`                       | Main library source                |
| `src/anyio/_backends/`             | Backend implementations            |
| `tests/`                           | Test suite (pytest + anyio plugin) |
| `docs/`                            | Sphinx documentation               |
| `docs/versionhistory.rst`          | Changelog                          |
| `.github/pull_request_template.md` | PR template (must be respected)    |
