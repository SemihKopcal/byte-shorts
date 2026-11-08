"""
SQLite yedegi (calisirken tutarli: sqlite3 backup API). Cron ile:
  docker compose exec -T panel python -m bytepanel.backup

Son N yedek tutulur. Yedek dosyalari 0600. Videolar R2'de, burada yalniz kayitlar var.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .db import utcnow


def backup(db_path: str, dest_dir: str, keep: int = 14, now=utcnow) -> Path:
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    target = dest / f"panel-{now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    os.chmod(target, 0o600)
    for old in sorted(dest.glob("panel-*.db"))[:-keep]:
        old.unlink()
    return target


def main() -> None:
    db = os.environ.get("PANEL_DB", "/data/panel.db")
    out = backup(db, os.path.join(os.path.dirname(db), "backups"))
    print(f"yedek alindi: {out}")


if __name__ == "__main__":
    main()
