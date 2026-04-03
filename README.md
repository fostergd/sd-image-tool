# SD Image Tool

SD Image Tool is a Windows desktop application for Raspberry Pi and SD card imaging workflows.

It can:

- save a physical SD card to an image file
- automatically shrink saved images with PiShrink when WSL support is available
- write an image file back to an SD card
- verify an image against an SD card
- guide the user through staged WSL + distro + PiShrink setup when shrink support is missing

## Current release

Current tagged release: **v0.1.1**

## Key behavior

### Runs elevated

The packaged Windows application is designed to run elevated at launch.

That is intentional. Raw physical drive read and write operations require administrative access.

### Save still works without WSL

If WSL or PiShrink is not installed, the app still supports:

- Save
- Write
- Verify

In that state, automatic shrink is skipped and the app explains why shrink is unavailable.

### Staged shrink setup

When shrink support is unavailable, the app presents a staged setup flow.

Typical stages are:

1. Install WSL
2. Install a Linux distribution
3. Install PiShrink and required Linux tools

After each stage, return to the app and click **Re-check Shrink Readiness**.

## Distributing the packaged app

Distribute the **full release zip**, not just the EXE.

The packaged app expects the folder layout created by the release build. The executable must remain next to its bundled support files.

Correct structure:

```text
SD Image Tool\
  SD Image Tool.exe
  _internal\
    python312.dll
    ...
```

Do not send only `SD Image Tool.exe` by itself.

## First run notes

### Antivirus scan on first launch

Some systems may perform a first-run scan of the packaged EXE. That is normal for a newly built or newly copied Windows executable.

### Windows elevation behavior

On many systems, launching the packaged EXE will trigger elevation.

On some systems, UAC policy may be configured to elevate administrators without prompting. In that case the app may simply open elevated without showing a visible UAC dialog.

## Build output

The Windows release build produces:

- a packaged app folder under `dist\SD Image Tool\`
- a distributable release zip under `releases\`

## Typical workflow

1. Launch SD Image Tool
2. Insert the SD card or card reader
3. Click **Refresh Device List** if needed
4. Save the SD card to an image
5. Let auto-shrink run if shrink support is ready
6. Write the image to another SD card when needed
7. Verify the written card against the selected image

## WSL and PiShrink setup

Shrink support uses WSL and PiShrink.

The app can guide the user through staged setup directly from the UI. Manual setup remains available from the app as help text when preferred.

## Release artifact recommendation

For end users, provide the zip created in `releases\`, extract it locally, and run the packaged EXE from the extracted folder.

## Known good validation summary

The following have been validated during development:

- Save works with and without shrink support
- Auto-shrink works after staged WSL/PiShrink setup
- Write succeeds and produces a bootable Raspberry Pi SD card
- Verify succeeds against a matching image and card
- Packaged release runs elevated and works from an extracted release zip

## Repository line endings

This repository uses `.gitattributes` to reduce LF/CRLF noise across Python, PowerShell, manifest, spec, and documentation files.
