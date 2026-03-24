from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

from sdtool.formatting import format_bytes


@dataclass(slots=True, frozen=True)
class VaultImage:
    path: Path
    size_bytes: int
    modified_time: datetime
    is_shrunk: bool
    original_filename: str | None = None
    imported_at: str | None = None

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def formatted_size(self) -> str:
        return format_bytes(self.size_bytes)

    @property
    def formatted_modified(self) -> str:
        return self.modified_time.strftime("%Y-%m-%d %H:%M")

    @property
    def status_text(self) -> str:
        return "Shrunk" if self.is_shrunk else "Original"


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def default_vault_path() -> Path:
    path = application_root() / "vault-images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def metadata_path(vault_path: Path) -> Path:
    return vault_path / "vault_metadata.json"


def _derive_is_shrunk(filename: str) -> bool:
    return "-shrunk" in Path(filename).stem.lower()


def load_metadata(vault_path: Path) -> dict[str, dict[str, Any]]:
    path = metadata_path(vault_path)
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(raw, dict):
        return {}

    cleaned: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, dict):
            cleaned[key] = value
    return cleaned


def save_metadata(vault_path: Path, metadata: dict[str, dict[str, Any]]) -> None:
    path = metadata_path(vault_path)
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")


def record_import_metadata(
    vault_path: Path,
    image_filename: str,
    *,
    is_shrunk: bool,
    original_filename: str,
    imported_at: str | None = None,
) -> None:
    metadata = load_metadata(vault_path)
    metadata[image_filename] = {
        "is_shrunk": is_shrunk,
        "original_filename": original_filename,
        "imported_at": imported_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_metadata(vault_path, metadata)


def next_available_image_path(vault_path: Path, preferred_name: str) -> Path:
    preferred = Path(preferred_name)
    stem = preferred.stem
    suffix = preferred.suffix.lower() or ".img"

    candidate = vault_path / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate

    index = 2
    while True:
        candidate = vault_path / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def scan_vault(vault_path: Path) -> list[VaultImage]:
    if not vault_path.exists():
        return []

    metadata = load_metadata(vault_path)
    images: list[VaultImage] = []

    for path in sorted(vault_path.glob("*.img")):
        if not path.is_file():
            continue

        stat = path.stat()
        entry = metadata.get(path.name, {})
        is_shrunk = bool(entry.get("is_shrunk", _derive_is_shrunk(path.name)))
        original_filename = entry.get("original_filename")
        imported_at = entry.get("imported_at")

        images.append(
            VaultImage(
                path=path,
                size_bytes=stat.st_size,
                modified_time=datetime.fromtimestamp(stat.st_mtime),
                is_shrunk=is_shrunk,
                original_filename=original_filename,
                imported_at=imported_at,
            )
        )

    images.sort(key=lambda item: item.modified_time, reverse=True)
    return images