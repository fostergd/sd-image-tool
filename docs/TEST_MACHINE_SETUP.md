# SD Image Tool Test Machine Setup

This checklist is for preparing a new Windows machine to test the development repo or the packaged release.

## Repo / development setup

1. Clone or copy the repo to the target machine.
2. Do **not** copy an existing `.venv` from another machine.
3. Create a fresh virtual environment on the target machine:
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -e .[dev]
   ```
4. Verify the interpreter and package import:
   ```powershell
   python --version
   where.exe python
   python -c "import sdtool, sys; print(sys.executable); print(sdtool.__file__)"
   ```
5. Run the local checks:
   ```powershell
   .\scripts\run_tests.ps1
   .\scripts\run_app.ps1
   ```

## No-WSL test machine setup

To test the staged WSL setup flow, remove or disable WSL first.

### Remove installed distributions
```powershell
wsl --list --verbose
wsl --unregister <DistributionName>
```

### Disable the WSL optional component
Use **Turn Windows features on or off** and clear **Windows Subsystem for Linux**, then reboot.

After reboot, this should fail or report that WSL is not installed:
```powershell
wsl --status
wsl --list --verbose
```

## Hardware testing notes

- Use a spare SD card when testing Write.
- For raw device access, the app must be running elevated.
- Connect USB readers/adapters directly to the Windows machine running the app.
- Disable sleep while testing long Save or Shrink operations.

## Packaged app smoke test

1. Extract the full release zip.
2. Do **not** copy only the EXE.
3. Confirm the folder layout contains:
   ```text
   SD Image Tool\
     SD Image Tool.exe
     _internal\
       python312.dll
       ...
   ```
4. Launch the EXE from the extracted folder.
5. Confirm it opens elevated.
6. Smoke test:
   - Save
   - Save → auto-shrink
   - Write
   - Verify
   - Boot a freshly written card in a Pi
