\# SD Image Tool - Agent Rules



\## Product rules

\- This app will be used on many Windows PCs with different hardware and software installed.

\- Optional tools such as WSL, PiShrink, and future external utilities must never be assumed to exist.

\- The app must detect optional dependencies at runtime and degrade gracefully when they are missing.

\- When an optional dependency is missing, the UI must explain what feature is unavailable, how to enable it, and a way to enable from within the app.

\- The app must still start and remain usable when optional dependencies are missing.



\## Architecture rules

\- Keep external-tool integrations behind adapter/backend layers.

\- Avoid mixing UI code with OS probing, disk I/O, or subprocess logic.

\- Prefer small, testable functions for parsing, detection, validation, and command planning.

\- New platform-specific features should be added in separate modules.



\## Safety rules

\- No destructive disk operations should be added casually.

\- Real disk read/write code must require strong validation and explicit user confirmation.

\- The app must reject fixed/system disks unless explicitly designed otherwise.

\- The app will be running from a usb drive of some kind and should reject that disk as a source/destination.

\- Default automated tests must never touch real disks.



\## Testing rules

\- Add tests for both dependency-present and dependency-missing paths.

\- Add tests for parsing and command-building logic whenever practical.

\- Keep the fast test suite runnable on a normal Windows machine without special hardware.



\## UX rules

\- The app should be simple and user friendly.

\- Long operations must clearly explain what is happening and when progress may appear to pause.

\- Show useful status, logs, output paths, sizes, and warnings.



\## AI workflow rules

\- Prefer small bounded edits over broad refactors.

\- Do not replace working code with placeholders like "existing code here".

\- Do not invent fake paths like path/to/file.py.

\- Keep existing working behavior unless the task explicitly changes it.

\- Keep shrink working while new features are added.

