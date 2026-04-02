# SD Image Tool Release Checklist

## Before building

- Confirm working tree is clean or intentionally staged
- Run the full automated test suite
- Confirm current version/tag target
- Confirm packaged icon and metadata are correct

## Development validation

- Save works on a machine without WSL
- Write works on a spare SD card
- Verify works on a matching SD card and image
- Shrink readiness text is readable
- Manual setup help is readable
- Staged setup button text is correct for the current readiness state

## Shrink validation

- On a machine without WSL, the app reports shrink unavailable cleanly
- Step 1 installs WSL when missing
- Step 2 installs or prepares a Linux distribution
- Step 3 installs PiShrink and required Linux tools
- Re-check Shrink Readiness reports Ready after setup
- Save triggers auto-shrink successfully when ready
- Original unshrunk image is deleted after successful auto-shrink when expected

## Packaging validation

- Run `scripts\build_windows_release.ps1`
- Confirm packaged folder exists under `dist\SD Image Tool\`
- Confirm release zip exists under `releases\`
- Launch packaged EXE from Explorer
- Confirm packaged app is elevated at startup
- Confirm icon appears correctly
- Confirm packaged Save works
- Confirm packaged auto-shrink works on a ready machine
- Confirm packaged Write works
- Confirm packaged Verify works

## Distribution validation

- Copy the release zip to another machine
- Extract locally
- Confirm `_internal\python312.dll` exists next to the EXE layout
- Launch packaged EXE from the extracted folder
- Confirm app runs correctly without using the original build tree

## Git and release steps

- Commit final release changes
- Push branch
- Create release tag
- Push release tag
- Upload the release zip to GitHub Releases
- Paste release notes into the GitHub release description

## Final artifact reminders

- Distribute the full release zip, not only the EXE
- Keep version number, tag, EXE metadata, and zip name aligned
