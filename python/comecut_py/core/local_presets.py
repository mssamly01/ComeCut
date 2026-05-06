"""Local JSON preset storage for ComeCut.

The preset layer is intentionally small: it stores user-created text/effect/
motion/export preset payloads as JSON files under a local directory. UI layers
can build richer workflows on top without changing the storage contract.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PRESET_CATEGORIES = {"text", "subtitle", "effect", "motion", "export", "audio", "project"}
DEFAULT_PRESET_ROOT = Path.home() / ".comecut_py" / "presets"
_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(frozen=True)
class LocalPreset:
    category: str
    name: str
    path: Path
    payload: dict[str, Any]


def slugify_preset_name(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").strip()).strip("-._").lower()
    return slug or "preset"


def validate_preset_category(category: str) -> str:
    cat = (category or "").strip().lower()
    if cat not in PRESET_CATEGORIES:
        allowed = ", ".join(sorted(PRESET_CATEGORIES))
        raise ValueError(f"Unknown preset category '{category}'. Expected one of: {allowed}")
    return cat


def preset_category_dir(category: str, *, root: Path | None = None) -> Path:
    return (root or DEFAULT_PRESET_ROOT) / validate_preset_category(category)


def preset_file_path(category: str, name: str, *, root: Path | None = None) -> Path:
    return preset_category_dir(category, root=root) / f"{slugify_preset_name(name)}.json"


def save_local_preset(
    category: str,
    name: str,
    payload: dict[str, Any],
    *,
    root: Path | None = None,
) -> Path:
    if not isinstance(payload, dict):
        raise TypeError("Preset payload must be a JSON object")
    cat = validate_preset_category(category)
    display_name = (name or "").strip() or "Preset"
    path = preset_file_path(cat, display_name, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "category": cat,
        "name": display_name,
        "payload": payload,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_local_preset(
    category: str,
    name: str,
    *,
    root: Path | None = None,
) -> LocalPreset:
    cat = validate_preset_category(category)
    path = preset_file_path(cat, name, root=root)
    data = json.loads(path.read_text(encoding="utf-8"))
    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError(f"Preset '{name}' has invalid payload")
    return LocalPreset(
        category=str(data.get("category") or cat),
        name=str(data.get("name") or name),
        path=path,
        payload=payload,
    )


def list_local_presets(category: str, *, root: Path | None = None) -> list[LocalPreset]:
    cat = validate_preset_category(category)
    folder = preset_category_dir(cat, root=root)
    if not folder.exists():
        return []
    presets: list[LocalPreset] = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            continue
        presets.append(
            LocalPreset(
                category=str(data.get("category") or cat),
                name=str(data.get("name") or path.stem),
                path=path,
                payload=payload,
            )
        )
    return presets


def delete_local_preset(category: str, name: str, *, root: Path | None = None) -> bool:
    path = preset_file_path(category, name, root=root)
    if not path.exists():
        return False
    path.unlink()
    return True


__all__ = [
    "DEFAULT_PRESET_ROOT",
    "PRESET_CATEGORIES",
    "LocalPreset",
    "delete_local_preset",
    "list_local_presets",
    "load_local_preset",
    "preset_category_dir",
    "preset_file_path",
    "save_local_preset",
    "slugify_preset_name",
    "validate_preset_category",
]
