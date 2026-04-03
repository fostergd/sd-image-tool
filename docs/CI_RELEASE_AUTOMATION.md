# CI and Release Automation

This repository uses two GitHub Actions workflows.

## CI workflow

File: `.github/workflows/ci.yml`

Runs on:
- pushes to `main`
- pull requests

What it does:
1. checks out the repo
2. creates a fresh `.venv`
3. installs the project in editable mode
4. installs `pytest` and `pyinstaller`
5. runs the test suite
6. performs a package smoke build and uploads the resulting zip as a workflow artifact

## Release workflow

File: `.github/workflows/release.yml`

Runs on:
- pushes of tags matching `v*`

What it does:
1. checks out the repo
2. creates a fresh `.venv`
3. installs the project and build dependencies
4. runs the test suite
5. builds the Windows release zip with `scripts/build_windows_release.ps1`
6. uploads the built zip as a workflow artifact
7. publishes or updates the GitHub Release for that tag and attaches the zip

## Release notes behavior

If a matching notes file exists at:

`docs/releases/<tag>-release-notes.md`

the release workflow uses that file as the release body.

Example:
- tag: `v0.1.1`
- notes file: `docs/releases/v0.1.1-release-notes.md`

If no matching notes file exists, GitHub generated release notes are used instead.

## Normal release process

1. Commit and push the final changes.
2. Create and push a tag:
   - `git tag v0.1.2`
   - `git push origin v0.1.2`
3. Wait for the Release workflow to finish.
4. Verify that the GitHub Release contains the Windows zip asset.
