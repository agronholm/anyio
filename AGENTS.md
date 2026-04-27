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

Every pull request **must** follow the PR template in `.github/pull_request_template.md`. Do **not** erase or replace the template contents — PRs that do so will be closed without review.

A properly filled-out PR contains:

### 1. Changes section
- Reference the related issue number, if applicable (e.g., `Fixes #123.`).
- Provide a short description of what the PR changes and why.

### 2. Checklist
Complete the checklist where applicable:
- **Tests** — Add or update tests in `tests/` that would fail without the patch.
- **Documentation** — Update docs in `docs/` if behavior changes or new features are introduced.
- **Changelog** — Add a new entry in `docs/versionhistory.rst`.

### 3. Changelog entry format
If there are no entries after the last release, use `**UNRELEASED**` as the version heading. An entry should look like:

```
- Fix big bad boo-boo in task groups
  (`#123 <https://github.com/agronholm/anyio/issues/123>`_; PR by @yourgithubaccount)
```

If there is no linked issue, link to the pull request itself instead (update the changelog after the PR is created to get the PR number).

Trivial changes (typo fixes, code reformatting) may skip the checklist items.

### 4. Good and bad examples

Here is a good example of a PR that adds a new feature: https://github.com/agronholm/anyio/pull/1100
Here is a bad example of a PR that overwrites the PR template and lacks tests and a changelog entry: https://github.com/agronholm/anyio/pull/1112

## Repository Layout

| Path | Description |
|---|---|
| `src/anyio/` | Main library source |
| `src/anyio/_backends/` | asyncio and Trio backend implementations |
| `tests/` | Test suite (pytest + anyio plugin) |
| `docs/` | Sphinx documentation |
| `docs/versionhistory.rst` | Changelog |
| `.github/pull_request_template.md` | PR template (must be respected) |
