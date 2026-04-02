# WSL / PiShrink Setup Troubleshooting

This document covers the staged WSL setup flow used by SD Image Tool.

## Step 1: Install WSL

Expected result:
- The helper enables the **Windows Subsystem for Linux** optional component.
- Windows may say a reboot is required.

Guidance:
- Reboot Windows before continuing, even if the prompt wording is unclear.
- After reboot, open the app again and click **Re-check Shrink Readiness**.

## Step 2: Install the Linux distro

Expected result:
- The helper installs the selected/default distro.
- On first run, the distro may ask for a Linux username and password.

Guidance:
- Complete the distro first-run prompts.
- If the distro window drops to a shell prompt afterward, type `exit` or close the window manually.
- Return to the app and click **Re-check Shrink Readiness**.

## Step 3: Install PiShrink and dependencies

Expected result:
- The helper installs:
  - `curl`
  - `parted`
  - `e2fsprogs`
  - `util-linux`
  - `coreutils`
  - `ca-certificates`
  - `pishrink.sh`
- You may be prompted for your Linux `sudo` password.

Guidance:
- The password will not be shown while typing.
- Type the password and press **Enter**.
- When the helper completes, return to the app and click **Re-check Shrink Readiness**.

## Common issues

### WSL is still shown as not installed after Step 1
Reboot Windows, then re-open the app and click **Re-check Shrink Readiness**.

### The distro window remains open after account creation
This is expected on some systems. Type `exit` or close the window manually, then continue.

### Kali / distro package source problems
If Step 3 reports repository signature, GPG, or package-source issues:
- fix the distro's package sources inside that distro
- re-run Step 3 from the app

### PiShrink fails later with missing Linux tools
Re-run **Step 3** from the app. The staged setup flow is designed to install PiShrink and its required Linux dependencies.

### Packaged app fails with missing `python312.dll`
This is usually a deployment issue:
- extract the **full release zip**
- do not copy only the EXE
- make sure `_internal\python312.dll` exists next to the EXE

## Verification after setup

After setup shows **Ready**, test:
- Save → auto-shrink
- Write
- Verify
- Boot the written card on a Raspberry Pi
