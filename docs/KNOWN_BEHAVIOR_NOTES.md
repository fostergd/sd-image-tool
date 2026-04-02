# Known Behavior Notes

These are behaviors that are expected or acceptable in the current release.

- On some systems, enabling the WSL optional component requires a reboot even if the user experience does not strongly emphasize it.
- After distro first-run account creation, the distro window may remain at a shell prompt. This is acceptable; the user can type `exit` or close the window manually.
- Antivirus may scan the packaged EXE on first launch from a new location. Subsequent launches are usually faster.
- Raw SD read/write operations require elevation.
- A card that has already been booted in a Raspberry Pi is no longer a clean byte-for-byte target for Verify against the pre-boot image.
