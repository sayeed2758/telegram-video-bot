#!/usr/bin/env python3
"""Restore SQLite databases from a Phase 36 backup ZIP.

Always stop the bot before restoring. Existing DB files are backed up beside
this script before replacement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_sqlite(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if not row or row[0] != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup_zip")
    args = parser.parse_args()

    archive = Path(args.backup_zip).resolve()
    if not archive.is_file():
        raise SystemExit(f"Backup not found: {archive}")

    restore_tmp = ROOT / ".restore_tmp"
    restore_tmp.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pre_restore = ROOT / "backups" / f"pre-restore-{stamp}"
    pre_restore.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive) as zf:
            names = set(zf.namelist())
            if "manifest.json" not in names:
                raise RuntimeError("Backup manifest.json is missing")
            manifest = json.loads(zf.read("manifest.json"))
            items = manifest.get("files", [])
            if not isinstance(items, list) or not items:
                raise RuntimeError("Backup contains no database manifest entries")

            for item in items:
                name = str(item["name"])
                if Path(name).name != name or not name.endswith(".sqlite3"):
                    raise RuntimeError(f"Unsafe database name in manifest: {name}")
                if name not in names:
                    raise RuntimeError(f"Database missing from backup: {name}")
                blob = zf.read(name)
                if sha256_bytes(blob) != item["sha256"]:
                    raise RuntimeError(f"Checksum mismatch: {name}")
                target = restore_tmp / name
                target.write_bytes(blob)
                validate_sqlite(target)

            DATA_DIR.mkdir(parents=True, exist_ok=True)
            for item in items:
                name = str(item["name"])
                current = DATA_DIR / name
                if current.exists():
                    current.replace(pre_restore / name)
                (restore_tmp / name).replace(current)
                print(f"Restored: {current}")

        print(f"Pre-restore backup: {pre_restore}")
        return 0
    finally:
        for child in restore_tmp.glob("*"):
            child.unlink(missing_ok=True)
        try:
            restore_tmp.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
