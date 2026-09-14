#!/usr/bin/env python3
"""Create a consistent ZIP backup of the bot's SQLite data files.

Usage:
    python tools/backup_data.py
    python tools/backup_data.py --output-dir backups
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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sqlite_snapshot(src: Path, dst: Path) -> None:
    """Use SQLite backup API for a consistent snapshot of a live DB."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(src, timeout=15) as source:
        source.execute("PRAGMA busy_timeout=15000")
        with sqlite3.connect(dst) as target:
            source.backup(target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(ROOT / "backups"))
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    dbs = sorted(DATA_DIR.glob("*.sqlite3"))
    if not dbs:
        print("No SQLite databases found in data/.")
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work_dir = output_dir / f".backup_{stamp}"
    work_dir.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, object] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Advance Tera Video Bot",
        "files": [],
    }

    try:
        for src in dbs:
            snap = work_dir / src.name
            sqlite_snapshot(src, snap)
            item = {
                "name": src.name,
                "sha256": sha256_file(snap),
                "size": snap.stat().st_size,
            }
            cast_files = manifest["files"]
            assert isinstance(cast_files, list)
            cast_files.append(item)

        (work_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        archive = output_dir / f"tera-video-bot-backup-{stamp}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(work_dir.iterdir()):
                zf.write(path, arcname=path.name)

        print(f"Backup created: {archive}")
        for item in manifest["files"]:
            print(f"  {item['name']}: {item['size']} bytes")
        print(f"  SHA256 manifest: {work_dir / 'manifest.json'}")
        return 0
    finally:
        for p in work_dir.iterdir():
            p.unlink(missing_ok=True)
        work_dir.rmdir()


if __name__ == "__main__":
    raise SystemExit(main())
