<!-- Thank you for your contribution! -->

**NOTE** Erasing or replacing the contents of this template will result in your pull
request being summarily closed without consideration!

## Changes

Fixes #. <!-- Provide issue number if exists -->

<!-- Please give a short brief about these changes. -->

## Checklist

If this is a user-facing code change, like a bugfix or a new feature, please ensure that
you've fulfilled the following conditions (where applicable):

- [ ] You've added tests (in `tests/`) which would fail without your patch
- [ ] You've updated the documentation (in `docs/`), in case of behavior changes or new
features
- [ ] You've added a changelog fragment (in `changelog.d/`).

If this is a trivial change, like a typo fix or a code reformatting, then you can ignore
these instructions.

### Updating the changelog

Add a news fragment file in the `changelog.d/` directory, named
`<issue or PR number>.<type>.rst`, where `<type>` is one of:

- `breaking`: backwards incompatible changes
- `added`: new features
- `changed`: other user-visible changes
- `fixed`: bug fixes

If, say, your patch fixes issue <span>#</span>123, create `changelog.d/123.fixed.rst`
containing only a brief summary of the change, like this:

```
Fixed big bad boo-boo in task groups
```

The issue link and the credit for your pull request are added automatically on release.
If there's no issue linked, name the file after your pull request instead by adding the
fragment after you've created the PR.
