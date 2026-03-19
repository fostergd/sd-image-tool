Read AGENTS.md first and follow it.



Project-specific rules:

\- Optional dependencies such as WSL, PiShrink, and future external utilities must never be assumed to exist.

\- When an optional dependency is missing, keep the app usable and explain what feature is unavailable, how to enable it, and a way to enable it from within the app.

\- Keep external-tool integrations behind adapter/backend layers.

\- Do not break working shrink behavior while adding new features.

\- No destructive disk operations without strong validation, explicit confirmation, and tests.

\- The app will run from removable storage, so reject the running app’s own disk as a source/destination.

\- Prefer small bounded edits over broad refactors.

\- Never replace working code with placeholders.

\- Never invent fake file paths.

\- Add tests for dependency-present and dependency-missing paths.

