#!/usr/bin/env python3
"""Patch SciPy module to avoid NameError in frozen PyInstaller builds.

Some SciPy versions can raise:
    NameError: name 'obj' is not defined
inside scipy.stats._distn_infrastructure when frozen in one-file EXE.
This script applies a minimal, idempotent source patch in the active venv.
"""

from __future__ import annotations

from pathlib import Path
import sys


TARGET_RELATIVE = Path("Lib/site-packages/scipy/stats/_distn_infrastructure.py")

OLD_BLOCK = (
    "for obj in [s for s in dir() if s.startswith('_doc_')]:\n"
    "    exec('del ' + obj)\n"
    "del obj"
)

NEW_BLOCK = (
    "for obj in [s for s in dir() if s.startswith('_doc_')]:\n"
    "    exec('del ' + obj)\n"
    "if 'obj' in locals():\n"
    "    del obj"
)


def main() -> int:
    target_file = Path(sys.prefix) / TARGET_RELATIVE
    if not target_file.exists():
        print(f"[ERROR] SciPy file not found: {target_file}")
        return 1

    content = target_file.read_text(encoding="utf-8")

    if NEW_BLOCK in content:
        print(f"[INFO] SciPy patch already applied: {target_file}")
        return 0

    if OLD_BLOCK not in content:
        print("[ERROR] Expected SciPy block was not found; patch aborted.")
        print(f"[INFO] Checked file: {target_file}")
        return 1

    patched = content.replace(OLD_BLOCK, NEW_BLOCK, 1)
    target_file.write_text(patched, encoding="utf-8")
    print(f"[INFO] Applied SciPy patch: {target_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
